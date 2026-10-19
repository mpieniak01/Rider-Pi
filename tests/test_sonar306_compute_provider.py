"""Compute/provider characterization uses scripted transports and observed fake state."""

import copy
import io
import json
import socket
from types import SimpleNamespace

import pytest
from flask import Flask
from test_compute_client import client_fixture as client_fixture, submit
from test_compute_runners import voice_runner

from apps.compute import stream_prepare
from apps.compute.client import ComputeError
from apps.compute.runners import FrameSource
from services import provider_watchdog
from services.api_core import provider_api, provider_observation


@pytest.mark.parametrize(
    "fields,error",
    [
        ({"metadata": [], "params": []}, "invalid_compute_metadata"),
        ({"params": [], "task": "invalid"}, "invalid_compute_params"),
        ({"task": "invalid", "data": b''}, "unsupported_compute_task_or_type"),
        ({"data": b''}, "compute_input_too_large_or_empty"),
    ],
)
def test_compute_input_rejection_precedes_session_or_job_mutation(client_fixture, fields, error):
    client, transport, _ = client_fixture
    args = {
        "task": "text.respond",
        "data": b'hello',
        "content_type": "text/plain; charset=utf-8",
        "metadata": {"captured_at": 999, "sequence": 1, "ttl_ms": 1000, "stream_id": "stream", "input_id": "input"},
    }
    args.update(fields)
    with pytest.raises(ComputeError, match=error):
        client.submit(**args)
    assert transport.calls == []
    assert client._jobs == {}
    assert client._submitted == {}
    assert client._lease is None


def test_compute_terminal_rejection_caches_observation_without_delivery(client_fixture):
    client, transport, _ = client_fixture
    job = submit(client)
    transport.state = "failed"
    with pytest.raises(ComputeError, match="compute_job_failed"):
        client.result(job)
    assert client._jobs[job].observation["state"] == "failed"
    assert client._delivered == {}
    assert len([r for r in transport.calls if r[0] == 'POST' and r[1] == '/jobs']) == 1


def test_compute_lost_post_receipt_is_cancelled_without_retry(client_fixture):
    client, transport, _ = client_fixture
    transport.fail_submit = True
    with pytest.raises(ComputeError, match="compute_transport_unavailable"):
        submit(client)
    methods = [(r[0], r[1]) for r in transport.calls]
    assert len([r for r in methods if r == ('POST', '/jobs')]) == 1
    assert methods[-1][0] == 'DELETE'
    assert client._submitted['test-stream'] == 1


def test_stream_response_header_delay_reduces_same_socket_budget():
    events = []
    clock = SimpleNamespace(now=10)

    class Response(io.BytesIO):
        def __enter__(self):
            clock.now += 0.3
            return self

        def __exit__(self, *_):
            self.close()

    response = Response(json.dumps({"stream": {}}).encode())
    response.fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=events.append)))
    opener = SimpleNamespace(open=lambda req, timeout: response)
    assert stream_prepare._read_stream_status(opener, object(), 0.8, 10.8, lambda: clock.now) == {"stream": {}}
    assert events[0] == pytest.approx(0.5)
    assert response.closed


def test_stream_timeout_is_stable_without_raw_url_or_token():
    def fail(*_args, **_kwargs):
        raise socket.timeout('private source')

    opener, request = SimpleNamespace(open=fail), object()

    def clock():
        return 0

    with pytest.raises(ComputeError, match="navigation_stream_prepare_timeout") as caught:
        stream_prepare._read_stream_status(opener, request, 0.2, 1, clock)
    assert caught.value.status == 504
    assert 'private source' not in str(caught.value)


def test_native_frame_initial_reference_is_consumed_once_and_preserves_capture(monkeypatch):
    from apps.camera import pipeline_ipc

    source = FrameSource.__new__(FrameSource)
    source.native, source.require_bytes, source.previous_frame, source.max_age_ms = True, False, None, 300
    row = {
        "camera_session": "session",
        "transport_epoch": 1,
        "pipeline_revision": 4,
        "sequence": 2,
        "frame_id": "session-2",
        "sha256": "a" * 64,
        "captured_monotonic_ns": 1_000_000_000,
    }
    initial = {**row, "sequence": 1, "frame_id": "session-1"}
    source.initial_source = initial
    monkeypatch.setattr(pipeline_ipc, 'read_frame', lambda **_: (None, row))
    monkeypatch.setattr('apps.compute.runners.time.monotonic_ns', lambda: 1_100_000_000)
    first = source.recv(20)
    second = source.recv(20)
    assert first["input_id"] == 'session-1'
    assert second["input_id"] == 'session-2'
    assert first["captured_monotonic_ns"] == initial["captured_monotonic_ns"]
    assert source.initial_source is None


def test_capture_playback_overlap_discards_partial_utterance_and_closes():
    class Capture:
        closed = 0

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def frames(self):
            yield b'\x00\x01' * 320

        def close(self):
            self.closed += 1

    capture = Capture()
    runner, client, _, _, _ = voice_runner(capture=capture)
    runner._current = lambda **_: None
    runner._health = lambda: None
    runner._speaker_state = lambda: SimpleNamespace(active=False, generation=1, quiet_until=0)
    overlap = iter([False, True])
    runner._speaker_overlapped = lambda _: next(overlap)
    assert runner.utterance() is None
    assert capture.closed == 1
    assert runner.capture is None
    assert client.requests == []
    runner.close()


def test_provider_remote_unready_task_cannot_claim_ready(monkeypatch):
    from services import compute_config

    state = {"domains": {}, "persisted": True}
    monkeypatch.setattr(provider_observation.registry, 'get_state_snapshot', lambda: state)
    monkeypatch.setattr(provider_observation.registry, 'get_health_snapshot', lambda: {})
    sample = {
        "stale": False,
        "state": "running",
        "response_task": [],
        "capabilities": {
            "tasks": {
                "text.respond": {"ready": True},
                "audio.transcribe": {"ready": True},
                "audio.synthesize": {"ready": False},
            }
        },
    }
    monkeypatch.setattr(
        compute_config,
        'observed_status',
        lambda: {"selected_executor": 'venom', "domains": {"voice": sample, "vision": {}}},
    )
    result = provider_observation.snapshot(now=1000)
    assert result['domains']['text']['ready'] is True
    assert result['domains']['voice']['ready'] is False
    assert result['domains']['voice']['effective'] == 'unavailable'
    assert result['partial'] is True


def test_provider_local_pid_mismatch_denies_loaded_model():
    worker = {
        "pid": 10,
        "observed_at": 1000,
        "domains": ['asr', 'tts'],
        "capabilities": {'asr': {"ready": True, "model_loaded": True}, 'tts': {"ready": True, "model_loaded": True}},
    }
    before = copy.deepcopy(worker)
    result = provider_observation._local('voice', worker, {"pid": 11, "active": 'active'}, 1000)
    assert result['ready'] is False
    assert result['initialized'] is False
    assert result['model_loaded'] is True
    assert worker == before


@pytest.mark.parametrize(
    'unexpected,status,reason', [(False, 'offline', 'pc_unreachable'), (True, 'error', 'pc_error')]
)
def test_watchdog_failure_records_without_refresh_then_marks_fallback(monkeypatch, unexpected, status, reason):
    events = []
    monkeypatch.setattr(provider_watchdog.registry, 'update_pc_health', lambda **kw: events.append(('health', kw)))
    monkeypatch.setattr(provider_watchdog, '_fallback_to_local', lambda why: events.append(('fallback', why)))
    count, state = provider_watchdog._capability_failure(
        OSError('fake'), provider_watchdog.FAIL_THRESHOLD - 1, None, unexpected=unexpected
    )
    assert count == provider_watchdog.FAIL_THRESHOLD
    assert state == status
    assert events[0][1]['refresh'] is False
    assert events[1] == ('fallback', reason)


def test_provider_bad_patch_has_no_registry_mutation(monkeypatch):
    monkeypatch.setattr(
        provider_api.registry, 'set_domain_mode', lambda *_args, **_kwargs: pytest.fail('invalid patch persisted')
    )
    app = Flask(__name__)
    app.add_url_rule('/provider/<domain>', view_func=provider_api.provider_domain_handler, methods=['PATCH'])
    response = app.test_client().patch('/provider/voice', json={"target": True})
    assert response.status_code == 400
    assert response.json['ok'] is False


@pytest.mark.parametrize(
    'failure_stage,exception,expected_status,unexpected',
    [
        ('none', None, 'online', None),
        ('fetch', TimeoutError('timeout'), 'offline', False),
        ('fetch', RuntimeError('decode failed'), 'offline', True),
        ('health', RuntimeError('registry failed'), 'offline', True),
        ('restore', RuntimeError('restore failed'), 'online', True),
    ],
)
def test_watchdog_cycle_preserves_prior_state_until_health_is_observed(
    monkeypatch, failure_stage, exception, expected_status, unexpected
):
    events = []

    def fetch(base_url):
        events.append(('fetch', base_url))
        if failure_stage == 'fetch':
            raise exception
        return {'version': 'fake-v1'}, 25

    def health(**fields):
        events.append(('health', fields))
        if failure_stage == 'health':
            raise exception

    def restore():
        events.append(('restore',))
        if failure_stage == 'restore':
            raise exception

    def failed(exc, failures, status, **kwargs):
        events.append(('failure', exc, failures, status, kwargs))
        return failures + 1, status

    monkeypatch.setattr(
        provider_watchdog, 'registry', SimpleNamespace(get_pc_base_url=lambda: None, update_pc_health=health)
    )
    monkeypatch.setattr(provider_watchdog, '_fetch_pc_capabilities', fetch)
    monkeypatch.setattr(provider_watchdog, '_restore_domains', restore)
    monkeypatch.setattr(provider_watchdog, '_capability_failure', failed)
    monkeypatch.setattr(provider_watchdog, 'time', SimpleNamespace(time=lambda: 1000))
    result = provider_watchdog._capability_cycle(7, 'offline')
    assert events[0] == ('fetch', provider_watchdog.DEFAULT_PC_BASE_URL)
    if exception is None:
        assert result == (0, 'online')
        assert [event[0] for event in events] == ['fetch', 'health', 'restore']
    else:
        assert result == (8, expected_status)
        assert events[-1] == ('failure', exception, 7, expected_status, {'unexpected': unexpected})
        assert [event[0] for event in events] == {
            'fetch': ['fetch', 'failure'],
            'health': ['fetch', 'health', 'failure'],
            'restore': ['fetch', 'health', 'restore', 'failure'],
        }[failure_stage]
    if failure_stage != 'fetch':
        assert events[1][1] == {
            'reachable': True,
            'status': 'online',
            'latency_ms': 25,
            'reason': 'fake-v1',
            'capabilities': {'version': 'fake-v1'},
            'observed_at': None,
            'received_at': 1000,
        }


@pytest.mark.parametrize(
    'version,cutoff,phase', [(2, None, 'ready'), (2, 9.7, 'ready'), (2, 9.8, 'turn_settling'), (3, 9.8, 'steer_wait')]
)
def test_navigation_frame_metadata_preserves_capture_cutoff_and_motion_phase(version, cutoff, phase):
    from apps.compute.navigation_cycle import NavigationCycle
    from services.navigation_config import DEFAULT

    cycle = NavigationCycle.__new__(NavigationCycle)
    cycle.policy = copy.deepcopy(DEFAULT)
    cycle.policy['avoidance'].update(enabled=True, protocol_version=version)
    cycle.clock = lambda: 10
    cycle.last_frame, cycle.run_id, cycle.sequence = ('input', 999), 'fake-run', 4
    cycle.turn_capture_after = cutoff
    captured, metadata = cycle._frame_metadata(200)
    assert captured == pytest.approx(9.8)
    assert cycle.started == 10
    assert cycle.fresh_frame_seen is True
    assert cycle.sequence == 5
    assert metadata['sequence'] == 5
    assert metadata['age_ms'] == 200
    assert metadata['motion_phase'] == phase
    assert metadata['protocol_version'] == version
    assert metadata['run_id'] == 'fake-run'
    assert metadata['avoidance'] == cycle.policy['avoidance']


@pytest.mark.parametrize(
    'domain,required',
    [
        ('vision', ['vision.describe']),
        ('text', ['text.respond']),
        ('voice', ['audio.transcribe', 'conversation.respond', 'audio.synthesize']),
    ],
)
def test_remote_provider_requires_only_selected_domain_tasks(domain, required):
    tasks = {name: {'ready': True} for name in required}
    sample = {
        'stale': False,
        'state': 'running',
        'response_task': 'conversation.respond',
        'capabilities': {'tasks': tasks},
    }
    compute = {'domains': {'vision': sample, 'voice': sample}}
    before = copy.deepcopy(compute)
    assert provider_observation._remote_domain(domain, 'venom', compute)['ready'] is True
    assert compute == before
    for task in required:
        tasks[task]['ready'] = False
        assert provider_observation._remote_domain(domain, 'venom', compute)['ready'] is False
        tasks[task]['ready'] = True


@pytest.mark.parametrize(
    'names,ready,error',
    [
        ((), True, None),
        (('chat',), True, None),
        (('chat',), False, 'backend_not_ready'),
        ((), False, 'provider_observation_unavailable'),
    ],
)
def test_local_provider_error_keeps_readiness_before_capability_availability(names, ready, error):
    assert provider_observation._local_error(names, ready) == error
