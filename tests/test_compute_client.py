"""Compute wire checks use scripted transport and an isolated loopback server."""

import http.client
import io
import json
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from apps.compute.client import ComputeClient, ComputeError, HTTPTransport, validate_wav


class Clock:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value

    def sleep(self, duration):
        self.value += duration


def wav():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b'\0\0' * 160)
    return buffer.getvalue()


class Transport:
    def __init__(self):
        self.calls = []
        self.jobs = {}
        self.closed = False
        self.state = 'succeeded'
        self.change = {}
        self.fail_submit = False
        self.executor_session = 'executor1'
        self.response_type = 'application/json'

    def request(self, method, path, headers, body, timeout):
        self.calls.append((method, path, headers, body, timeout))
        if path == '/capabilities':
            data = {'executor_id': 'venom', 'executor_session': self.executor_session, 'tasks': {}}
        elif path == '/sessions':
            data = {
                **json.loads(body),
                'session_id': 'session1',
                'device_id': 'test',
                'executor_id': 'venom',
                'executor_session': self.executor_session,
            }
        elif path == '/jobs' and method == 'POST':
            if self.fail_submit:
                raise ComputeError('compute_transport_unavailable')
            metadata = json.loads(headers['X-Rider-Job'])
            self.jobs[metadata['job_id']] = metadata
            data = self.observation(metadata['job_id'], 'queued')
        elif path.endswith('/output'):
            return 200, {'Content-Type': 'audio/wav'}, wav()
        elif method == 'GET':
            data = self.observation(path.rsplit('/', 1)[1], self.state)
            data.update(self.change)
        else:
            return 204, {}, b''
        return 200, {'Content-Type': self.response_type}, json.dumps({'protocol_version': 1, **data}).encode()

    def observation(self, job_id, state):
        return {
            **self.jobs[job_id],
            'device_id': 'test',
            'state': state,
            'runtime': {'model': 'real'},
            'quality': {'simulated': False},
            'metrics': {'source_age_ms': 5},
            'data': {'text': 'ok'},
            'output_available': True,
            'received_at': 1000,
            'finished_at': 1000,
        }

    def close(self):
        self.closed = True


class PreparationTransport(Transport):
    def __init__(self, clock, *, delay=4.0, session_delay=0.0):
        super().__init__()
        self.clock, self.delay, self.session_delay = clock, delay, session_delay

    def request(self, method, path, headers, body, timeout):
        if path in {'/capabilities', '/sessions'}:
            self.clock.sleep(self.session_delay)
        if method == 'POST' and path == '/jobs':
            if self.delay > timeout:
                self.calls.append((method, path, headers, body, timeout))
                self.clock.sleep(timeout)
                raise ComputeError('compute_transport_unavailable')
            self.clock.sleep(self.delay)
        return super().request(method, path, headers, body, timeout)


def test_voice_asr_submit_allows_bounded_preparation_without_renewing_ttl():
    clock = Clock()
    transport = PreparationTransport(clock, session_delay=1.0)
    with ComputeClient(
        'http://fixture.invalid',
        'test',
        'test-token',
        'boot1',
        client_id='voice',
        transport=transport,
        clock=clock,
        wall_clock=clock,
        sleeper=clock.sleep,
    ) as client:
        job = submit(client, task='audio.transcribe')
        posted = [call for call in transport.calls if call[:2] == ('POST', '/jobs')]
        assert len(posted) == 1
        assert posted[0][4] == 15.0
        assert json.loads(posted[0][2]['X-Rider-Job'])['ttl_ms'] == 28000
        assert client._jobs[job].deadline == 1030.0
        assert client.result(job)['state'] == 'succeeded'
        assert all(call[4] <= 2 for call in transport.calls if call[:2] != ('POST', '/jobs'))


def test_voice_asr_preparation_cannot_exceed_remaining_ttl_or_retry():
    clock = Clock()
    transport = PreparationTransport(clock, session_delay=1.0)
    with ComputeClient(
        'http://fixture.invalid',
        'test',
        'test-token',
        'boot1',
        client_id='voice',
        transport=transport,
        clock=clock,
        wall_clock=clock,
        sleeper=clock.sleep,
    ) as client:
        with pytest.raises(ComputeError, match='compute_transport_unavailable'):
            submit(client, task='audio.transcribe', ttl_ms=5000)
        posted = [call for call in transport.calls if call[:2] == ('POST', '/jobs')]
        assert len(posted) == 1
        assert posted[0][4] == 3.0
        assert json.loads(posted[0][2]['X-Rider-Job'])['ttl_ms'] == 3000
        assert clock() == 1005.0
        assert len([call for call in transport.calls if call[0] == 'DELETE']) == 1
        assert not client._jobs


@pytest.mark.parametrize(
    'client_id,task', [('panel', 'audio.transcribe'), ('voice', 'text.respond'), ('voice', 'audio.synthesize')]
)
def test_other_compute_submissions_keep_the_short_timeout(client_id, task):
    clock = Clock()
    transport = PreparationTransport(clock, delay=3.0)
    with ComputeClient(
        'http://fixture.invalid',
        'test',
        'test-token',
        'boot1',
        client_id=client_id,
        transport=transport,
        clock=clock,
        wall_clock=clock,
        sleeper=clock.sleep,
    ) as client:
        with pytest.raises(ComputeError, match='compute_transport_unavailable'):
            submit(client, task=task)
        posted = [call for call in transport.calls if call[:2] == ('POST', '/jobs')]
        assert len(posted) == 1
        assert posted[0][4] == 2.0


@pytest.fixture
def client_fixture():
    clock = Clock()
    transport = Transport()
    client = ComputeClient(
        'http://fixture.invalid',
        'test',
        'test-token',
        'boot1',
        transport=transport,
        clock=clock,
        wall_clock=clock,
        sleeper=clock.sleep,
        client_id='vision',
    )
    yield client, transport, clock
    client.close()


def submit(client, *, task='text.respond', sequence=1, captured_at=999.0, ttl_ms=30000, stream='test-stream'):
    content_type = (
        'audio/wav'
        if task == 'audio.transcribe'
        else ('image/jpeg' if task == 'vision.describe' else 'text/plain; charset=utf-8')
    )
    body = wav() if task == 'audio.transcribe' else b'hello'
    return client.submit(
        task,
        body,
        content_type,
        {'captured_at': captured_at, 'sequence': sequence, 'input_id': 'input1', 'stream_id': stream, 'ttl_ms': ttl_ms},
        params={'language': 'pl'},
    )


def test_constructor_is_idle_and_auth_header_is_private(client_fixture):
    client, transport, _ = client_fixture
    assert transport.calls == []
    job = submit(client)
    assert client.result(job)['data']['text'] == 'ok'
    assert all(call[2]['Authorization'] == 'Bearer test-token' for call in transport.calls)
    session = json.loads(next(call[3] for call in transport.calls if call[1] == '/sessions'))
    assert session['client_id'] == 'vision'
    assert session['client_instance'] == client.client_instance
    assert 'test-token' not in repr(client)
    assert client.identity['session_id'] == 'session1'
    assert client.identity['client_id'] == 'vision'
    assert 'token' not in client.identity
    assert 'url' not in client.identity


def test_binary_payload_preserves_source_identity(client_fixture):
    client, transport, _ = client_fixture
    job = submit(client, task='audio.transcribe')
    request = next(call for call in transport.calls if call[1] == '/jobs' and call[0] == 'POST')
    assert request[3] == wav()
    header = json.loads(request[2]['X-Rider-Job'])
    assert header['job_id'] == job
    assert header['captured_at'] == 999.0
    assert header['input_age_ms'] == 1000
    assert header['sequence'] == 1


@pytest.mark.parametrize(
    'field,value',
    [
        ('job_id', 'old'),
        ('device_session', 'oldboot'),
        ('executor_session', 'oldexecutor'),
        ('session_id', 'oldlease'),
        ('device_id', 'other'),
        ('stream_id', 'other'),
        ('input_id', 'other'),
        ('captured_at', 1000),
        ('sequence', 2),
        ('task', 'vision.describe'),
    ],
)
def test_drops_wrong_correlation(client_fixture, field, value):
    client, transport, _ = client_fixture
    job = submit(client)
    transport.change[field] = value
    with pytest.raises(ComputeError, match='stale_compute_result'):
        client.result(job)


@pytest.mark.parametrize('captured_at', [None, True, float('nan'), float('inf'), 0, 1002])
def test_missing_nonfinite_or_old_capture_is_never_refreshed(client_fixture, captured_at):
    client, transport, _ = client_fixture
    with pytest.raises(ComputeError):
        submit(client, captured_at=captured_at)
    assert transport.calls == []


def test_old_or_duplicate_segments_are_rejected_without_transport(client_fixture):
    client, transport, _ = client_fixture
    submit(client, sequence=2)
    count = len(transport.calls)
    with pytest.raises(ComputeError, match='stale_compute_sequence'):
        submit(client, sequence=2)
    assert len(transport.calls) == count


def test_monotonic_deadline_cancels_no_post_retry(client_fixture):
    client, transport, clock = client_fixture
    transport.state = 'running'
    job = submit(client, ttl_ms=200)
    with pytest.raises(ComputeError, match='compute_deadline_expired'):
        client.result(job)
    assert clock.value < 1001
    assert sum(call[0] == 'POST' and call[1] == '/jobs' for call in transport.calls) == 1
    assert any(call[:2] == ('DELETE', '/jobs/' + job) for call in transport.calls)


def test_lost_ack_is_cancelled_and_never_retried(client_fixture):
    client, transport, _ = client_fixture
    transport.fail_submit = True
    with pytest.raises(ComputeError, match='compute_transport_unavailable'):
        submit(client)
    assert sum(call[:2] == ('POST', '/jobs') for call in transport.calls) == 1
    assert any(call[0] == 'DELETE' and call[1].startswith('/jobs/') for call in transport.calls)


def test_latest_image_rejects_late_old_result(client_fixture):
    client, _, _ = client_fixture
    old = submit(client, task='vision.describe', sequence=1)
    new = submit(client, task='vision.describe', sequence=2)
    assert client.result(new)['sequence'] == 2
    with pytest.raises(ComputeError, match='superseded_compute_result'):
        client.result(old)


@pytest.mark.parametrize('state', ['failed', 'expired', 'cancelled', 'superseded'])
def test_terminal_failure_is_not_mock_success(client_fixture, state):
    client, transport, _ = client_fixture
    job = submit(client)
    transport.state = state
    with pytest.raises(ComputeError, match='compute_job_' + state):
        client.result(job)


def test_tts_output_is_validated_and_connection_closes_own_lease(client_fixture):
    client, transport, _ = client_fixture
    job = submit(client, task='audio.synthesize')
    assert client.output(job) == wav()
    client.close()
    assert transport.closed
    assert ('DELETE', '/sessions/session1') in [call[:2] for call in transport.calls]
    with pytest.raises(ComputeError, match='compute_client_closed'):
        client.capabilities()


def test_json_mime_is_required(client_fixture):
    client, transport, _ = client_fixture
    transport.response_type = 'text/html'
    with pytest.raises(ComputeError, match='invalid_compute_response_type'):
        client.capabilities()


def test_job_buffer_is_bounded(client_fixture):
    client, transport, _ = client_fixture
    for index in range(5):
        submit(client, sequence=index + 1)
    count = len(transport.calls)
    with pytest.raises(ComputeError, match='compute_client_saturated'):
        submit(client, sequence=6)
    assert len(transport.calls) == count


@pytest.mark.parametrize(
    'url',
    [
        None,
        [],
        {},
        '',
        'ftp://localhost',
        'http://user:pass@localhost',
        'http://localhost/x',
        'http://localhost?key=secret',
        'http://localhost/#x',
    ],
)
def test_rejects_ambiguous_transport_address(url):
    with pytest.raises(ComputeError, match='invalid_compute_url'):
        HTTPTransport(url)


def test_http_uses_one_request_no_redirect_following():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(307)
            self.send_header('Location', 'http://fixture.invalid/elsewhere')
            self.send_header('Content-Length', '0')
            self.end_headers()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    transport = HTTPTransport(f'http://127.0.0.1:{server.server_port}')
    try:
        status, _, _ = transport.request('POST', '/jobs', {'Content-Type': 'audio/wav'}, wav(), 1)
        assert status == 307
        assert received == [('/api/v1/rider/compute/jobs', wav())]
    finally:
        transport.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_http_replaces_server_closed_idle_connection_before_post(monkeypatch):
    clock = Clock()
    received, attempts = [], []
    closed = threading.Event()
    original = http.client.HTTPConnection.request

    def record_attempt(connection, method, path, *args, **kwargs):
        attempts.append((method, path))
        return original(connection, method, path, *args, **kwargs)

    monkeypatch.setattr(http.client.HTTPConnection, 'request', record_attempt)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def respond(self):
            received.append((self.command, self.path))
            if self.command == 'POST':
                self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'{}')
            # Like an idle timeout: close without a Connection: close header.
            self.close_connection = True

        do_GET = do_POST = respond

        def log_message(self, *_):
            pass

    class Server(ThreadingHTTPServer):
        def shutdown_request(self, connection):
            super().shutdown_request(connection)
            closed.set()

    server = Server(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    transport = HTTPTransport(f'http://127.0.0.1:{server.server_port}', clock=clock)
    try:
        assert transport.request('GET', '/capabilities', {}, b'', 1)[0] == 200
        assert closed.wait(timeout=1)
        previous = transport.connection
        assert previous.sock is not None  # Peer closed; the client still retains the socket.
        clock.sleep(5.1)  # Capture delay, no real sleep.
        assert transport.request('POST', '/sessions', {}, b'{}', 1)[0] == 200
        assert transport.connection is not previous
        expected = [('GET', '/api/v1/rider/compute/capabilities'), ('POST', '/api/v1/rider/compute/sessions')]
        assert attempts == expected
        assert received == expected
    finally:
        transport.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_http_short_polling_reuses_connection_and_idle_starts_after_response(monkeypatch):
    clock = Clock()
    connections = []

    class Response:
        status = 200

        def read(self, _limit):
            clock.sleep(1.0)
            return b'{}'

        def getheaders(self):
            return [('Content-Type', 'application/json')]

    class Connection:
        sock = None

        def __init__(self, *_args, **_kwargs):
            self.closed = False
            connections.append(self)

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            self.closed = True

    monkeypatch.setattr(http.client, 'HTTPConnection', Connection)
    transport = HTTPTransport('http://127.0.0.1', clock=clock)
    try:
        transport.request('GET', '/capabilities', {}, b'', 2)
        clock.sleep(1.5)
        transport.request('POST', '/sessions', {}, b'{}', 2)
        assert len(connections) == 1
        assert not connections[0].closed
        clock.sleep(2.0)
        transport.request('GET', '/capabilities', {}, b'', 2)
        assert len(connections) == 2
        assert connections[0].closed
    finally:
        transport.close()


def test_invalid_audio_does_not_load_any_engine():
    with pytest.raises(ComputeError, match='invalid_compute_audio'):
        validate_wav(b'not-wav')


def test_handshake_counts_towards_monotonic_budget(client_fixture):
    client, transport, clock = client_fixture
    original = transport.request

    def slow_handshake(method, path, *args):
        if path == '/sessions':
            clock.sleep(0.5)
        return original(method, path, *args)

    transport.request = slow_handshake
    with pytest.raises(ComputeError, match='compute_deadline_expired'):
        submit(client, ttl_ms=200)
    assert not any(call[:2] == ('POST', '/jobs') for call in transport.calls)


@pytest.mark.parametrize('metric', [-1, 'fresh', True])
def test_invalid_source_metrics_are_rejected(client_fixture, metric):
    client, transport, _ = client_fixture
    job = submit(client)
    transport.change['metrics'] = {'source_age_ms': metric}
    with pytest.raises(ComputeError, match='invalid_compute_job_metrics'):
        client.result(job)


def test_error_codes_preserve_saturation_without_exposing_body(client_fixture):
    client, transport, _ = client_fixture
    transport.request = lambda *args: (
        429,
        {'Content-Type': 'application/json'},
        b'{"detail":{"code":"compute_saturated","details":{"token":"private"}}}',
    )
    with pytest.raises(ComputeError) as raised:
        client.capabilities()
    assert raised.value.status == 429
    assert raised.value.code == 'compute_saturated'
    assert 'private' not in str(raised.value)


def test_conversation_task_is_only_for_voice_client(client_fixture):
    client, transport, _ = client_fixture
    with pytest.raises(ComputeError, match='conversation_voice_only'):
        submit(client, task='conversation.respond')
    assert not transport.calls
    client.client_id = 'voice'
    job = submit(client, task='conversation.respond')
    assert client.result(job)['task'] == 'conversation.respond'


@pytest.mark.parametrize('language', [{}, [], ['pl'], None, True, 1, 'fr'])
def test_invalid_transcription_language_is_typed_400_before_transport(client_fixture, language):
    client, transport, _ = client_fixture
    audio = wav()
    with pytest.raises(ComputeError, match='invalid_compute_params') as raised:
        client.submit(
            'audio.transcribe',
            audio,
            'audio/wav',
            {'captured_at': 999, 'sequence': 1, 'input_id': 'sample', 'stream_id': 'voice'},
            params={'language': language},
        )
    assert raised.value.status == 400
    assert not transport.calls


@pytest.mark.parametrize('params', [[], 'pl', True, 3])
def test_non_object_params_is_typed_400_before_transport(client_fixture, params):
    client, transport, _ = client_fixture
    audio = wav()
    with pytest.raises(ComputeError, match='invalid_compute_params') as raised:
        client.submit(
            'audio.transcribe',
            audio,
            'audio/wav',
            {'captured_at': 999, 'sequence': 1, 'input_id': 'sample', 'stream_id': 'voice'},
            params=params,
        )
    assert raised.value.status == 400
    assert not transport.calls


@pytest.mark.parametrize('url', ['http://venom-host:8000', 'http://10.0.0.1:8000', 'http://[2001:db8::1]'])
def test_private_client_rejects_nonloopback_http_before_sending_token(url):
    with pytest.raises(ComputeError, match='compute_https_or_loopback_required') as raised:
        ComputeClient(url, 'test', 'fixture-only-token', 'boot')
    assert raised.value.status == 400
    assert 'fixture-only-token' not in str(raised.value)


@pytest.mark.parametrize(
    'url,secure',
    [
        ('https://fixture.invalid:8443', True),
        ('http://localhost:8000', False),
        ('http://127.0.0.2:8000', False),
        ('http://[::1]:8000', False),
    ],
)
def test_https_and_loopback_transport_are_idle_and_allowed(url, secure):
    transport = HTTPTransport(url)
    assert transport.secure is secure
    assert transport.connection is None
    transport.close()
