"""Compute v1 transport. No hardware, local inference or persistent job replay."""

from __future__ import annotations

import contextlib
import http.client
import io
import json
import math
import re
import threading
import time
import uuid
import wave
from dataclasses import dataclass
from typing import Any

from common.compute_url import validate_compute_url

IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TASK_TYPES = {
    'conversation.respond': {'text/plain; charset=utf-8'},
    'text.respond': {'text/plain; charset=utf-8'},
    'audio.transcribe': {'audio/wav'},
    'audio.synthesize': {'text/plain; charset=utf-8'},
    'vision.describe': {'image/jpeg', 'image/png'},
}
TERMINAL = {'succeeded', 'failed', 'cancelled', 'expired', 'superseded'}
MAX_BYTES = 2 * 1024 * 1024


class ComputeError(RuntimeError):
    """Stable diagnostic code; never includes credentials or raw response text."""

    def __init__(self, code: str, status: int = 0) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ComputeError('invalid_compute_identifier')
    return value


def _number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value)


def validate_wav(data: bytes) -> int:
    """Validate bounded mono PCM16 audio without an ML/audio dependency."""
    try:
        with wave.open(io.BytesIO(data), 'rb') as audio:
            rate = audio.getframerate()
            frames = audio.getnframes()
            if (
                audio.getnchannels() != 1
                or audio.getsampwidth() != 2
                or audio.getcomptype() != 'NONE'
                or not 8000 <= rate <= 48000
                or not 0 < frames <= 15 * rate
                or len(audio.readframes(frames)) != frames * 2
            ):
                raise ValueError('unsupported audio')
            return rate
    except (EOFError, wave.Error, ValueError):
        raise ComputeError('invalid_compute_audio') from None


class HTTPTransport:
    """One keepalive connection; every request happens exactly once."""

    def __init__(self, base_url: str) -> None:
        try:
            parsed = validate_compute_url(base_url, allow_api_path=True)
        except ValueError as exc:
            raise ComputeError(str(exc), 400) from None
        self.host, self.port, self.secure = parsed.hostname, parsed.port, parsed.scheme == 'https'
        self.connection = None
        self.lock = threading.Lock()
        self.closed = False

    def request(self, method: str, path: str, headers: dict, body: bytes, timeout: float) -> tuple:
        with self.lock:
            if self.closed:
                raise ComputeError('compute_client_closed')
            if self.connection is None:
                cls = http.client.HTTPSConnection if self.secure else http.client.HTTPConnection
                self.connection = cls(self.host, self.port, timeout=timeout)
            connection = self.connection
            connection.timeout = timeout
            if connection.sock is not None:
                connection.sock.settimeout(timeout)
            try:
                connection.request(method, '/api/v1/rider/compute' + path, body=body, headers=headers)
                response = connection.getresponse()
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ComputeError('compute_response_too_large')
                return response.status, dict(response.getheaders()), data
            except (OSError, http.client.HTTPException):
                connection.close()
                self.connection = None
                raise ComputeError('compute_transport_unavailable') from None

    def close(self) -> None:
        self.closed = True
        if self.connection is not None:
            self.connection.close()
            self.connection = None


@dataclass
class PendingJob:
    header: dict
    deadline: float
    observation: dict | None = None


class ComputeClient:
    """An active goal's lease. Constructing the client does not open a socket."""

    def __init__(
        self,
        base_url: str,
        device_id: str,
        token: str,
        device_session: str,
        executor_id: str = 'venom',
        *,
        client_id: str = 'cli',
        transport=None,
        clock=time.monotonic,
        wall_clock=time.time,
        sleeper=time.sleep,
    ) -> None:
        self.device_id = _identifier(device_id)
        self.device_session = _identifier(device_session)
        self.executor_id = _identifier(executor_id)
        if client_id not in {'voice', 'vision', 'cli', 'panel'}:
            raise ComputeError('invalid_compute_client_id')
        self.client_id = client_id
        self.client_instance = uuid.uuid4().hex
        if not isinstance(token, str) or not token or len(token) > 4096 or '\r' in token or '\n' in token:
            raise ComputeError('compute_token_missing_or_invalid')
        self._headers = {'Authorization': 'Bearer ' + token, 'X-Rider-Device': self.device_id}
        self._transport = transport or HTTPTransport(base_url)
        self._clock, self._wall_clock, self._sleep = clock, wall_clock, sleeper
        self._lease: dict | None = None
        self._jobs: dict[str, PendingJob] = {}
        self._submitted: dict[str, int] = {}
        self._delivered: dict[str, int] = {}
        self._closed = False

    def _request(self, method: str, path: str, body: bytes = b'', headers=None, timeout: float = 2.0):
        if self._closed:
            raise ComputeError('compute_client_closed')
        status, response_headers, data = self._transport.request(
            method, path, {**self._headers, **(headers or {})}, body, max(0.01, min(timeout, 2.0))
        )
        if len(data) > MAX_BYTES:
            raise ComputeError('compute_response_too_large')
        if 200 <= status < 300:
            return response_headers, data
        code = 'compute_http_error'
        try:
            candidate = json.loads(data)['detail']['code']
            if isinstance(candidate, str) and re.fullmatch('[a-zA-Z0-9_]{1,100}', candidate):
                code = candidate
        except (ValueError, TypeError, KeyError):
            pass
        raise ComputeError(code, status)

    def _json(self, method: str, path: str, body: bytes = b'', headers=None, timeout: float = 2.0) -> dict:
        response_headers, data = self._request(method, path, body, headers, timeout)
        mime = next((v for k, v in response_headers.items() if k.lower() == 'content-type'), '')
        if mime.split(';')[0].strip().lower() != 'application/json':
            raise ComputeError('invalid_compute_response_type')
        try:
            result = json.loads(data, parse_constant=lambda _: None)
        except (ValueError, UnicodeDecodeError):
            raise ComputeError('invalid_compute_response') from None
        if (
            not isinstance(result, dict)
            or type(result.get('protocol_version')) is not int
            or result['protocol_version'] != 1
        ):
            raise ComputeError('unsupported_compute_protocol')
        return result

    def capabilities(self) -> dict:
        data = self._json('GET', '/capabilities')
        if data.get('executor_id') != self.executor_id or not isinstance(data.get('tasks'), dict):
            raise ComputeError('invalid_compute_capabilities')
        _identifier(data.get('executor_session'))
        if self._lease and data['executor_session'] != self._lease['executor_session']:
            raise ComputeError('stale_executor_session', 409)
        return data

    @property
    def identity(self) -> dict:
        lease = self._lease or {}
        return {
            'executor_id': self.executor_id,
            'executor_session': lease.get('executor_session'),
            'client_id': self.client_id,
            'client_instance': self.client_instance,
            'session_id': lease.get('session_id'),
            'device_id': self.device_id,
            'device_session': self.device_session,
        }

    def _session(self) -> dict:
        if self._lease is None:
            capabilities = self.capabilities()
            lease = self._json(
                'POST',
                '/sessions',
                json.dumps(
                    {
                        'protocol_version': 1,
                        'device_session': self.device_session,
                        'client_id': self.client_id,
                        'client_instance': self.client_instance,
                    }
                ).encode(),
                {'Content-Type': 'application/json'},
            )
            if any(
                lease.get(key) != expected
                for key, expected in {
                    'executor_id': self.executor_id,
                    'executor_session': capabilities['executor_session'],
                    'device_id': self.device_id,
                    'device_session': self.device_session,
                    'client_id': self.client_id,
                    'client_instance': self.client_instance,
                }.items()
            ):
                raise ComputeError('stale_compute_session', 409)
            _identifier(lease.get('session_id'))
            self._lease = lease
        return self._lease

    def submit(self, task: str, data: bytes, content_type: str, metadata: dict, params=None) -> str:
        started = self._clock()
        if task == 'conversation.respond' and self.client_id != 'voice':
            raise ComputeError('conversation_voice_only', 403)
        if not isinstance(metadata, dict):
            raise ComputeError('invalid_compute_metadata', 400)
        if params is not None and not isinstance(params, dict):
            raise ComputeError('invalid_compute_params', 400)
        if task not in TASK_TYPES or content_type not in TASK_TYPES[task]:
            raise ComputeError('unsupported_compute_task_or_type')
        if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
            raise ComputeError('compute_input_too_large_or_empty', 413)
        if task in {'text.respond', 'conversation.respond', 'audio.synthesize'}:
            if len(data) > 4096:
                raise ComputeError('compute_text_too_large', 413)
            try:
                data.decode('utf-8')
            except UnicodeDecodeError:
                raise ComputeError('invalid_compute_text') from None
        elif task == 'audio.transcribe':
            validate_wav(data)
        captured = metadata.get('captured_at')
        timestamp_source = metadata.get('timestamp_source', 'unknown')
        sequence = metadata.get('sequence')
        ttl = metadata.get('ttl_ms', 30000)
        if (
            not _number(captured)
            or not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 0
            or not isinstance(ttl, int)
            or isinstance(ttl, bool)
            or not 100 <= ttl <= 60000
            or timestamp_source not in {'capture', 'file_mtime', 'capture_read_boundary', 'operator_input', 'unknown'}
        ):
            raise ComputeError('invalid_compute_metadata')
        age = (self._wall_clock() - captured) * 1000
        if not -1000 <= age <= 60000:
            raise ComputeError('compute_source_expired', 409)
        stream = _identifier(metadata.get('stream_id'))
        if stream not in self._submitted and len(self._submitted) >= 64:
            raise ComputeError('compute_stream_limit', 429)
        input_id = _identifier(metadata.get('input_id'))
        if sequence <= self._submitted.get(stream, -1):
            raise ComputeError('stale_compute_sequence', 409)
        if len(self._jobs) >= 32:
            for job_id, pending in list(self._jobs.items()):
                if pending.observation and pending.observation.get('state') in TERMINAL:
                    self._jobs.pop(job_id)
                    break
        if sum(job.observation is None for job in self._jobs.values()) >= 5:
            raise ComputeError('compute_client_saturated', 429)
        params = dict(params or {})
        language = params.get('language', 'pl')
        if not isinstance(language, str) or language not in {'pl', 'en', 'de'} or set(params) - {'language', 'prompt'}:
            raise ComputeError('invalid_compute_params', 400)
        if 'prompt' in params and (task != 'vision.describe' or not isinstance(params['prompt'], str)):
            raise ComputeError('invalid_compute_params', 400)
        if len(params.get('prompt', '')) > 512:
            raise ComputeError('invalid_compute_params', 400)
        lease = self._session()
        remaining = int(ttl - (self._clock() - started) * 1000)
        age = max(0, round((self._wall_clock() - captured) * 1000))
        if remaining < 100 or age > 60000:
            raise ComputeError('compute_deadline_expired', 408)
        job_id = uuid.uuid4().hex
        header = {
            'protocol_version': 1,
            'executor_session': lease['executor_session'],
            'session_id': lease['session_id'],
            'device_session': self.device_session,
            'job_id': job_id,
            'input_id': input_id,
            'task': task,
            'captured_at': captured,
            'timestamp_source': timestamp_source,
            'input_age_ms': age,
            'ttl_ms': remaining,
            'sequence': sequence,
            'stream_id': stream,
            'params': params,
        }
        encoded = json.dumps(header, separators=(',', ':'), allow_nan=False)
        if len(encoded.encode()) > 4096:
            raise ComputeError('compute_job_header_too_large')
        # Register before POST so a lost acknowledgement can still be cancelled;
        # never retry that intention under either the same or a new identifier.
        pending = PendingJob(header, started + ttl / 1000)
        self._jobs[job_id] = pending
        self._submitted[stream] = sequence
        try:
            observation = self._json('POST', '/jobs', data, {'Content-Type': content_type, 'X-Rider-Job': encoded})
            self._validate(pending, observation)
        except Exception:
            with contextlib.suppress(ComputeError):
                self.cancel(job_id)
            raise
        return job_id

    def _validate(self, pending: PendingJob, observation: dict) -> None:
        correlation = {
            key: pending.header[key]
            for key in (
                'job_id',
                'task',
                'device_session',
                'executor_session',
                'session_id',
                'input_id',
                'stream_id',
                'sequence',
                'captured_at',
            )
        }
        correlation['device_id'] = self.device_id
        if any(observation.get(key) != value for key, value in correlation.items()):
            raise ComputeError('stale_compute_result', 409)
        if observation.get('state') not in TERMINAL | {'queued', 'running'}:
            raise ComputeError('invalid_compute_job_state')
        if any(not isinstance(observation.get(key), dict) for key in ('runtime', 'quality', 'metrics', 'data')):
            raise ComputeError('invalid_compute_job_observation')
        for name in ('queue_ms', 'inference_ms', 'source_age_ms'):
            value = observation['metrics'].get(name)
            if value is not None and (not _number(value) or value < 0):
                raise ComputeError('invalid_compute_job_metrics')
        if not _number(observation.get('received_at')) or (
            observation.get('finished_at') is not None and not _number(observation['finished_at'])
        ):
            raise ComputeError('invalid_compute_job_timestamp')
        if self._clock() >= pending.deadline:
            raise ComputeError('compute_deadline_expired', 408)

    def result(self, job_id: str, timeout: float = 30.0, stop_event=None, on_poll=None) -> dict:
        pending = self._jobs.get(_identifier(job_id))
        if pending is None:
            raise ComputeError('unknown_compute_job')
        if not _number(timeout) or timeout <= 0:
            raise ComputeError('invalid_compute_timeout')
        deadline = min(pending.deadline, self._clock() + timeout)
        while self._clock() < deadline:
            if self._closed or (stop_event is not None and stop_event.is_set()):
                raise ComputeError('compute_cancelled')
            observation = pending.observation or self._json(
                'GET', '/jobs/' + job_id, timeout=max(0.01, deadline - self._clock())
            )
            self._validate(pending, observation)
            if on_poll is not None:
                on_poll(observation)
            state = observation['state']
            if state in TERMINAL:
                pending.observation = observation
                if state != 'succeeded':
                    raise ComputeError('compute_job_' + state)
                stream, sequence = pending.header['stream_id'], pending.header['sequence']
                if sequence < self._delivered.get(stream, -1) or (
                    pending.header['task'] == 'vision.describe' and sequence < self._submitted[stream]
                ):
                    raise ComputeError('superseded_compute_result', 409)
                self._delivered[stream] = sequence
                return observation
            delay = min(0.1, max(0, deadline - self._clock()))
            if stop_event is not None:
                stop_event.wait(delay)
            else:
                self._sleep(delay)
        with contextlib.suppress(ComputeError):
            self.cancel(job_id)
        raise ComputeError('compute_deadline_expired', 408)

    def output(self, job_id: str) -> bytes:
        pending = self._jobs.get(_identifier(job_id))
        if pending is None or pending.header['task'] != 'audio.synthesize':
            raise ComputeError('compute_output_unavailable')
        observation = self.result(job_id)
        if observation.get('output_available') is not True:
            raise ComputeError('compute_output_unavailable')
        headers, data = self._request('GET', '/jobs/' + job_id + '/output')
        mime = next((v for k, v in headers.items() if k.lower() == 'content-type'), '')
        if mime.split(';')[0].lower() != 'audio/wav':
            raise ComputeError('invalid_compute_output_type')
        self._validate(pending, observation)
        validate_wav(data)
        return data

    def cancel(self, job_id: str) -> None:
        job_id = _identifier(job_id)
        if job_id in self._jobs:
            try:
                self._request('DELETE', '/jobs/' + job_id)
            finally:
                self._jobs.pop(job_id, None)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._lease is not None:
                with contextlib.suppress(ComputeError):
                    self._transport.request(
                        'DELETE',
                        '/sessions/' + self._lease['session_id'],
                        self._headers,
                        b'',
                        0.5,
                    )
        finally:
            self._closed = True
            self._jobs.clear()
            self._lease = None
            self._transport.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
