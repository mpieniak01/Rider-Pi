"""Goal-owned capture and playback; compute observations never reach actuators."""

from __future__ import annotations

import contextlib
import io
import logging
import math
import os
import struct
import threading
import time
import uuid
import wave
from collections import deque
from pathlib import Path

from .client import ComputeClient, ComputeError, validate_wav

LOG = logging.getLogger('compute')


def selected_executor():
    from services.compute_config import selected_executor as selected

    return selected()


def device_session() -> str:
    """Both media services share the boot identity, but hold independent leases."""
    try:
        value = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        return uuid.UUID(value).hex
    except (OSError, ValueError):
        # Process-scoped fallback never restores intentions from a previous run.
        return _PROCESS_SESSION


_PROCESS_SESSION = uuid.uuid4().hex


class FrameSource:
    """Subscribe to the existing camera owner; never open a V4L2 device."""

    def __init__(self) -> None:
        from common.frame_stream import FrameStreamClient

        self.client = FrameStreamClient(
            os.getenv('FRAME_STREAM_ADDR', 'tcp://127.0.0.1:5562'),
            os.getenv('FRAME_STREAM_TOPIC', 'camera.frame.raw'),
            latest=True,
            max_pending=2,
            encoded=True,
        )

    def recv(self, timeout_ms: int) -> dict | None:
        data = self.client.recv(timeout_ms)
        if not isinstance(data, bytes) or not data:
            return None
        metadata = self.client.metadata
        captured = metadata.get('captured_at')
        timestamp_source = 'capture'
        if captured is None:
            captured = metadata.get('mtime')
            timestamp_source = 'file_mtime'
        if isinstance(captured, bool) or not isinstance(captured, (int, float)) or not math.isfinite(captured):
            return None
        if data.startswith(b'\xff\xd8\xff'):
            content_type = 'image/jpeg'
        elif data.startswith(b'\x89PNG\r\n\x1a\n'):
            content_type = 'image/png'
        else:
            return None
        frame_id = metadata.get('id')
        input_id = metadata.get('frame_id') or (
            'frame-' + str(frame_id) if isinstance(frame_id, int) and frame_id >= 0 else 'frame-' + uuid.uuid4().hex
        )
        return {
            'data': data,
            'captured_at': captured,
            'input_id': input_id,
            'content_type': content_type,
            'timestamp_source': timestamp_source,
        }

    def close(self) -> None:
        self.client.close()


class GoalRunner:
    def __init__(
        self,
        domain: str,
        selection: dict,
        *,
        selector=selected_executor,
        client_factory=ComputeClient,
        publisher=None,
        on_status=None,
        stop_event=None,
        clock=time.monotonic,
        wall_clock=time.time,
    ) -> None:
        self.domain = domain
        self.selection = dict(selection)
        self.selector = selector
        self.client_factory = client_factory
        self.publisher = publisher
        self.on_status = on_status
        self.stop_event = stop_event or threading.Event()
        self.clock, self.wall_clock = clock, wall_clock
        self.client = None
        self.source = None
        self.capture = None
        self.sequence = 0
        self.closed = False
        self.next_selection_check = 0.0
        self.next_heartbeat = 0.0
        self.last_error = None
        self.capability_snapshot = None
        self.next_capability_check = 0.0

    def _current(self, *, force=False) -> None:
        if self.stop_event.is_set() or self.closed:
            raise ComputeError('compute_cancelled')
        if not force and self.clock() < self.next_selection_check:
            return
        self.next_selection_check = self.clock() + 1.0
        selected = self.selector()
        if not selected or any(
            selected.get(key) != self.selection.get(key) for key in ('id', 'revision', 'url', 'device_id')
        ):
            raise ComputeError('compute_selection_changed', 409)

    def _start(self, tasks: set[str]) -> None:
        self._current()
        if not tasks.issubset(set(self.selection.get('tasks', []))):
            raise ComputeError('compute_task_not_selected')
        self.client = self.client_factory(
            self.selection['url'],
            self.selection['device_id'],
            self.selection.get('token', ''),
            device_session(),
            self.selection['id'],
            client_id=self.domain,
        )
        capabilities = self.client.capabilities()
        self.capability_snapshot = capabilities
        self.next_capability_check = self.clock() + 10.0
        for task in tasks:
            capability = capabilities['tasks'].get(task)
            if not isinstance(capability, dict) or capability.get('available') is not True:
                raise ComputeError('compute_engine_unavailable', 503)
        self.status('waiting_for_input')

    def status(self, state: str, **data) -> None:
        identity = getattr(self.client, 'identity', {}) if self.client is not None else {}
        if self.capability_snapshot and identity.get('executor_session') is None:
            identity = {**identity, 'executor_session': self.capability_snapshot.get('executor_session')}
        observation = {
            'domain': self.domain,
            'state': state,
            'observed_at': self.wall_clock(),
            'selected_executor': self.selection['id'],
            'capabilities': self.capability_snapshot,
            **identity,
            **data,
        }
        try:
            if self.on_status is not None:
                self.on_status(observation)
            else:
                from services.compute_config import record_status

                record_status(self.domain, observation, revision=self.selection['revision'])
        except (OSError, ValueError, ImportError):
            LOG.warning('compute status cache unavailable')

    def emit(self, observation: dict, topic: str = 'compute.result') -> None:
        self._current(force=True)
        if self.publisher is not None:
            self.publisher.publish(topic, observation, add_ts=False)
        self.status(
            'succeeded',
            **{
                key: observation[key]
                for key in (
                    'job_id',
                    'input_id',
                    'captured_at',
                    'task',
                    'runtime',
                    'quality',
                    'metrics',
                    'data',
                )
                if key in observation
            },
        )

    def _heartbeat(self, state: str, **data) -> None:
        if self.clock() >= self.next_heartbeat:
            self.next_heartbeat = self.clock() + 5.0
            self.status(state, **data)

    def _poll(self, observation: dict) -> None:
        self._current()
        self._health()
        self._heartbeat(
            observation['state'],
            **{
                key: observation[key]
                for key in (
                    'job_id',
                    'input_id',
                    'captured_at',
                    'task',
                    'runtime',
                    'quality',
                    'metrics',
                )
                if key in observation
            },
        )

    def _health(self) -> None:
        if self.client is not None and self.capture is None and self.clock() >= self.next_capability_check:
            self.next_capability_check = self.clock() + 10.0
            self.capability_snapshot = self.client.capabilities()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.stop_event.set()
        for resource in (self.capture, self.source, self.client, self.publisher):
            if resource is not None:
                with contextlib.suppress(Exception):
                    resource.close()
        self.capture = self.source = self.client = self.publisher = None
        self.status('off', **({'error': self.last_error} if self.last_error else {}))

    def stop(self) -> None:
        self.close()

    def _failed(self, exc: Exception) -> None:
        code = exc.code if isinstance(exc, ComputeError) else 'compute_runner_failed'
        self.last_error = code
        self.status('unavailable', error=code)
        LOG.warning('compute %s: %s', self.domain, code)


class VisionRunner(GoalRunner):
    """Serial latest-frame scene descriptions, separate from obstacle/navigation."""

    def __init__(self, selection: dict, *, source_factory=FrameSource, language='pl', interval_s=1.0, **kwargs) -> None:
        super().__init__('vision', selection, **kwargs)
        self.source_factory = source_factory
        self.language = language
        self.interval_s = max(0.2, min(10.0, interval_s))
        self.last_input = None

    def step(self) -> dict | None:
        self._current()
        self._health()
        self._heartbeat('waiting_for_frame')
        frame = self.source.recv(250)
        if not frame or (frame.get('input_id'), frame.get('captured_at')) == self.last_input:
            return None
        captured = frame.get('captured_at')
        if (
            isinstance(captured, bool)
            or not isinstance(captured, (int, float))
            or not math.isfinite(captured)
            or not 0 <= self.wall_clock() - captured <= 60
        ):
            self.status('source_unavailable', error='camera_capture_time_unavailable')
            return None
        self.sequence += 1
        self.last_input = (frame['input_id'], captured)
        job_id = self.client.submit(
            'vision.describe',
            frame['data'],
            frame['content_type'],
            {
                'captured_at': captured,
                'input_id': frame['input_id'],
                'stream_id': 'vision',
                'sequence': self.sequence,
                'ttl_ms': 60000,
                'timestamp_source': frame.get('timestamp_source', 'unknown'),
            },
            params={'language': self.language},
        )
        observation = self.client.result(job_id, timeout=60, stop_event=self.stop_event, on_poll=self._poll)
        self._current(force=True)
        observation['quality'] = {
            **observation['quality'],
            'timestamp_source': frame.get('timestamp_source', 'unknown'),
        }
        self.emit(observation, 'vision.scene')
        return observation

    def run(self, *, once: bool = False) -> int:
        result = 0
        try:
            self._start({'vision.describe'})
            self.source = self.source_factory()
            while not self.stop_event.is_set():
                self.step()
                if once:
                    break
                self.stop_event.wait(self.interval_s)
        except Exception as exc:
            if not self.stop_event.is_set():
                self._failed(exc)
                result = 2
        finally:
            self.close()
        return result


def wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)
    return output.getvalue()


class VoiceRunner(GoalRunner):
    """Bounded utterance -> Venom STT -> text -> TTS. Never runs robot NLU."""

    def __init__(
        self, selection: dict, cfg: dict, *, capture_factory=None, playback=None, playback_observer=None, **kwargs
    ) -> None:
        super().__init__('voice', selection, **kwargs)
        from apps.voice.audio.capture import AudioCapture, CaptureConfig
        from apps.voice.audio.ownership import PlaybackObserver
        from apps.voice.audio.playback import PlaybackConfig, play_bytes

        self.cfg = cfg
        self.capture_cfg = CaptureConfig(**dict(cfg.get('capture') or {}))
        if (
            self.capture_cfg.channels != 1
            or self.capture_cfg.sample_format != 'S16_LE'
            or not 8000 <= self.capture_cfg.sample_rate <= 48000
            or self.capture_cfg.frame_ms > 100
        ):
            raise ComputeError('unsupported_compute_capture_format')
        # Continuous reads while collecting; close capture before inference so
        # buffered old microphone bytes cannot be relabelled as a new utterance.
        self.capture_cfg.buffer_seconds = 0
        self.capture_factory = capture_factory or AudioCapture
        self.playback = playback or play_bytes
        self.playback_observer = playback_observer or PlaybackObserver(clock=self.clock)
        self.playback_cfg = PlaybackConfig(**dict(cfg.get('playback') or {}))
        service, vad = cfg.get('service') or {}, cfg.get('vad') or {}
        self.gate = max(1, int(service.get('silence_rms_gate', 200)))
        self.max_frames = max(1, int(min(15000, max(200, vad.get('max_len_ms', 5000))) / self.capture_cfg.frame_ms))
        self.tail_frames = max(1, int(vad.get('tail_ms', 220) / self.capture_cfg.frame_ms))
        self.wait_frames = max(1, int(service.get('no_speech_timeout_ms', 3000) / self.capture_cfg.frame_ms))
        self.language = cfg.get('lang', 'pl')

    def _speaker_state(self):
        try:
            return self.playback_observer.snapshot()
        except (OSError, ValueError) as exc:
            raise ComputeError('compute_playback_state_unavailable', 503) from exc

    def _speaker_overlapped(self, generation) -> bool:
        state = self._speaker_state()
        return state.active or state.generation != generation or state.quiet_until > self.clock()

    def close(self) -> None:
        super().close()
        self.playback_observer.close()

    def utterance(self) -> tuple[bytes, float] | None:
        self._current()
        self._health()
        speaker = self._speaker_state()
        if speaker.active or speaker.quiet_until > self.clock():
            self._heartbeat('waiting_for_playback')
            return None
        capture_owner = self.capture_factory(self.capture_cfg)
        self.capture = capture_owner
        pre = deque(maxlen=max(1, int(200 / self.capture_cfg.frame_ms)))
        chunks, started, silent, waited = [], None, 0, 0
        try:
            with capture_owner as capture:
                if self._speaker_overlapped(speaker.generation):
                    self.status('playback_suppressed', error='voice_playback_overlap')
                    return None
                for frame in capture.frames():
                    self._current()
                    if self._speaker_overlapped(speaker.generation):
                        self.status('playback_suppressed', error='voice_playback_overlap')
                        return None
                    self._heartbeat('listening')
                    if not isinstance(frame, bytes) or len(frame) != self.capture_cfg.frame_bytes:
                        raise ComputeError('invalid_compute_capture_frame')
                    samples = list(struct.iter_unpack('<h', frame))
                    energy = math.sqrt(sum(sample[0] ** 2 for sample in samples) / len(samples))
                    voiced = energy >= self.gate
                    if started is None:
                        waited += 1
                        pre.append(frame)
                        if not voiced:
                            if waited >= self.wait_frames:
                                return None
                            continue
                        started = self.wall_clock() - len(pre) * self.capture_cfg.frame_duration_s
                        chunks.extend(pre)
                    else:
                        chunks.append(frame)
                    silent = 0 if voiced else silent + 1
                    if silent >= self.tail_frames or len(chunks) >= self.max_frames:
                        break
        finally:
            capture_owner.close()
            self.capture = None
        # Includes playback inside capture.close or between the last two frames.
        # Never keep pre-roll/partial speech to resume after the speaker stops.
        if self._speaker_overlapped(speaker.generation):
            self.status('playback_suppressed', error='voice_playback_overlap')
            return None
        if started is None:
            return None
        return wav_bytes(b''.join(chunks), self.capture_cfg.sample_rate), started

    def process(self, audio: bytes, captured_at: float, *, input_id: str | None = None) -> dict:
        self._current()
        self.sequence += 1
        sequence = self.sequence
        input_id = input_id or uuid.uuid4().hex
        deadline = self.clock() + 60

        def infer(task, data, content_type):
            self._current(force=True)
            ttl = min(60000, int((deadline - self.clock()) * 1000))
            if ttl < 100:
                raise ComputeError('compute_deadline_expired', 408)
            job_id = self.client.submit(
                task,
                data,
                content_type,
                {
                    'captured_at': captured_at,
                    'input_id': input_id,
                    'stream_id': 'voice-' + task.split('.')[1],
                    'sequence': sequence,
                    'ttl_ms': ttl,
                    'timestamp_source': 'capture_read_boundary',
                },
                params={'language': self.language},
            )
            observation = self.client.result(
                job_id,
                timeout=ttl / 1000,
                stop_event=self.stop_event,
                on_poll=self._poll,
            )
            self._current(force=True)
            self.emit(observation)
            return job_id, observation

        _, transcript = infer('audio.transcribe', audio, 'audio/wav')
        text = transcript['data'].get('text')
        if not isinstance(text, str):
            raise ComputeError('invalid_compute_transcript')
        if not text.strip():
            self.status('waiting_for_input', silence=True)
            return transcript
        conversation = (self.capability_snapshot or {}).get('tasks', {}).get('conversation.respond', {})
        response_task = (
            'conversation.respond'
            if ('conversation.respond' in self.selection.get('tasks', []) and conversation.get('available') is True)
            else 'text.respond'
        )
        _, response = infer(response_task, text.encode('utf-8'), 'text/plain; charset=utf-8')
        if response_task == 'conversation.respond' and response['data'].get('speech_played') is True:
            return response
        reply = response['data'].get('text')
        if not isinstance(reply, str) or not reply.strip():
            raise ComputeError('invalid_compute_reply')
        job_id, speech = infer('audio.synthesize', reply.encode('utf-8'), 'text/plain; charset=utf-8')
        output = self.client.output(job_id)
        rate = validate_wav(output)
        self._current(force=True)
        if not self.playback(output, 'wav', self.playback_cfg, sample_rate=rate, stop_event=self.stop_event):
            raise ComputeError('compute_playback_failed')
        return speech

    def run(self, *, once: bool = False) -> int:
        result = 0
        try:
            self._start({'audio.transcribe', 'text.respond', 'audio.synthesize'})
            while not self.stop_event.is_set():
                utterance = self.utterance()
                if utterance is not None:
                    self.process(*utterance)
                if once:
                    break
                self.stop_event.wait(0.1)
        except Exception as exc:
            if not self.stop_event.is_set():
                self._failed(exc)
                result = 2
        finally:
            self.close()
        return result
