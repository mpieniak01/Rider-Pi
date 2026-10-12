"""Media acceptance without robot, camera, microphone, playback or production BUS."""

import struct
import threading
from types import SimpleNamespace

import pytest

from apps.compute.client import ComputeError
from apps.compute.runners import FrameSource, VisionRunner, VoiceRunner, wav_bytes

TASKS = ['text.respond', 'audio.transcribe', 'audio.synthesize', 'vision.describe']


def selection():
    return {
        'id': 'venom',
        'url': 'http://fixture.invalid',
        'device_id': 'test',
        'token': 'test-token',
        'revision': 1,
        'tasks': TASKS,
    }


class Client:
    def __init__(self):
        self.requests = []
        self.closed = False
        self.tasks = {task: {'available': True, 'ready': False, 'model_loaded': False} for task in TASKS}
        self.transcript = 'jedź do przodu'
        self.result_hook = None
        self.capability_calls = 0

    def capabilities(self):
        self.capability_calls += 1
        return {'tasks': self.tasks}

    def submit(self, task, data, content_type, metadata, params):
        self.requests.append((task, data, content_type, metadata, params))
        return str(len(self.requests))

    def result(self, job_id, **_):
        task, _, _, metadata, _ = self.requests[int(job_id) - 1]
        if self.result_hook:
            self.result_hook(task)
        text = self.transcript if task == 'audio.transcribe' else 'opis lub odpowiedź'
        return {
            'task': task,
            **metadata,
            'state': 'succeeded',
            'runtime': {'model': 'fixture'},
            'quality': {'simulated': True},
            'metrics': {'source_age_ms': 1000},
            'data': {'text': text},
        }

    def output(self, _):
        return wav_bytes(b'\0\0' * 160, 16000)

    def close(self):
        self.closed = True


class Publisher:
    def __init__(self):
        self.messages = []
        self.closed = False

    def publish(self, topic, observation, **_):
        self.messages.append((topic, observation))

    def close(self):
        self.closed = True


class Source:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.closed = False

    def recv(self, _):
        return next(self.frames, None)

    def close(self):
        self.closed = True


def vision_runner(frames, *, selected=None):
    selected = selected or selection()
    client, source, publisher, statuses = Client(), Source(frames), Publisher(), []
    runner = VisionRunner(
        selected,
        selector=lambda: selected,
        client_factory=lambda *a, **k: client,
        source_factory=lambda: source,
        publisher=publisher,
        on_status=statuses.append,
        wall_clock=lambda: 1000,
    )
    return runner, client, source, publisher, statuses


def test_vision_uses_source_time_and_only_scene_topic():
    runner, client, source, publisher, _ = vision_runner(
        [
            {'data': b'jpeg', 'captured_at': 999, 'input_id': 'camera-12', 'content_type': 'image/jpeg'},
        ]
    )
    assert runner.run(once=True) == 0
    assert client.requests[0][3]['captured_at'] == 999
    assert client.requests[0][3]['input_id'] == 'camera-12'
    assert [topic for topic, _ in publisher.messages] == ['vision.scene']
    assert source.closed and client.closed and publisher.closed


@pytest.mark.parametrize('timestamp', [None, True, float('nan'), 0, 1001])
def test_vision_missing_stale_or_future_time_never_becomes_now(timestamp):
    runner, client, source, _, statuses = vision_runner(
        [
            {'data': b'jpeg', 'captured_at': timestamp, 'input_id': 'camera-12', 'content_type': 'image/jpeg'},
        ]
    )
    assert runner.run(once=True) == 0
    assert not client.requests
    assert source.closed
    assert any(status['state'] == 'source_unavailable' for status in statuses)


def test_vision_model_unavailable_does_not_open_camera_subscription():
    runner, client, source, _, statuses = vision_runner([])
    client.tasks['vision.describe']['available'] = False
    assert runner.run(once=True) == 2
    assert not source.closed  # Factory was never called; it owns no handle.
    assert client.closed
    assert any(status.get('error') == 'compute_engine_unavailable' for status in statuses)


def test_vision_off_does_not_connect_or_read_source():
    runner, client, source, _, _ = vision_runner([])
    runner.stop()
    assert runner.run(once=True) == 0
    assert not client.requests and not source.closed


def test_vision_duplicate_frame_not_resubmitted():
    frame = {'data': b'jpeg', 'captured_at': 999, 'input_id': 'camera-12', 'content_type': 'image/jpeg'}
    runner, client, source, _, _ = vision_runner([frame, frame])
    runner._start({'vision.describe'})
    runner.source = source
    try:
        assert runner.step()
        assert runner.step() is None
        assert len(client.requests) == 1
    finally:
        runner.close()


def test_late_vision_result_after_selection_change_is_dropped():
    selected = selection()
    runner, client, _, publisher, statuses = vision_runner(
        [
            {'data': b'jpeg', 'captured_at': 999, 'input_id': 'camera-12', 'content_type': 'image/jpeg'},
        ],
        selected=selected,
    )
    client.result_hook = lambda _: selected.update(revision=2)
    assert runner.run(once=True) == 2
    assert not publisher.messages
    assert any(status.get('error') == 'compute_selection_changed' for status in statuses)


class Capture:
    def __init__(self, frames):
        self.values = frames
        self.closed = False
        self.entered = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *_):
        self.close()

    def frames(self):
        yield from self.values

    def close(self):
        self.closed = True


def voice_runner(*, transcript='cześć', selected=None, capture=None, playback_observer=None, **runner_options):
    selected = selected or selection()
    client, publisher, statuses, playback = Client(), Publisher(), [], []
    client.transcript = transcript
    runner = VoiceRunner(
        selected,
        {
            'lang': 'pl',
            'capture': {'sample_rate': 16000, 'frame_ms': 20},
            'vad': {'tail_ms': 40},
            'service': {'no_speech_timeout_ms': 100},
        },
        selector=lambda: selected,
        client_factory=lambda *a, **k: client,
        capture_factory=lambda _: capture,
        publisher=publisher,
        on_status=statuses.append,
        playback=lambda *a, **k: playback.append((a, k)) or True,
        playback_observer=playback_observer,
        wall_clock=lambda: 1000,
        **runner_options,
    )
    return runner, client, publisher, statuses, playback


def test_voice_full_remote_chain_no_robot_command_and_shared_capture_time():
    runner, client, publisher, _, playback = voice_runner(transcript='jedź do przodu')
    try:
        runner._start({'audio.transcribe', 'text.respond', 'audio.synthesize'})
        runner.process(wav_bytes(b'\0\0' * 320, 16000), 999, input_id='utterance-1')
        assert [request[0] for request in client.requests] == [
            'audio.transcribe',
            'text.respond',
            'audio.synthesize',
        ]
        assert all(request[3]['captured_at'] == 999 for request in client.requests)
        assert all(request[3]['input_id'] == 'utterance-1' for request in client.requests)
        assert {topic for topic, _ in publisher.messages} == {'compute.result'}
        assert client.requests[1][1] == 'jedź do przodu'.encode()
        assert playback[0][1]['sample_rate'] == 16000
        assert playback[0][1]['stop_event'] is runner.stop_event
    finally:
        runner.close()
    assert client.closed and publisher.closed


def test_transcription_silence_is_healthy_and_no_fallback_or_reply():
    runner, client, _, statuses, playback = voice_runner(transcript='')
    try:
        runner._start({'audio.transcribe', 'text.respond', 'audio.synthesize'})
        runner.process(wav_bytes(b'\0\0' * 320, 16000), 999)
        assert len(client.requests) == 1 and not playback
        assert any(status.get('silence') is True for status in statuses)
    finally:
        runner.close()


def test_selection_change_between_stages_prevents_text_and_playback():
    selected = selection()
    runner, client, publisher, _, playback = voice_runner(selected=selected)
    client.result_hook = lambda _: selected.update(revision=2)
    try:
        runner._start({'audio.transcribe', 'text.respond', 'audio.synthesize'})
        with pytest.raises(ComputeError, match='compute_selection_changed'):
            runner.process(wav_bytes(b'\0\0' * 320, 16000), 999)
        assert len(client.requests) == 1 and not playback and not publisher.messages
    finally:
        runner.close()


def test_utterance_capture_closes_before_inference_and_retains_read_boundary_time():
    voiced = struct.pack('<h', 1000) * 320
    silent = b'\0\0' * 320
    capture = Capture([silent, voiced, voiced, silent, silent])
    runner, client, _, _, playback = voice_runner(capture=capture)
    original_submit = client.submit

    def submit(*args, **kwargs):
        assert capture.closed
        return original_submit(*args, **kwargs)

    client.submit = submit
    assert runner.run(once=True) == 0
    assert capture.closed and capture.entered and playback
    assert client.requests[0][3]['captured_at'] == pytest.approx(999.96)


def test_idle_silence_does_not_submit_inference():
    capture = Capture([b'\0\0' * 320] * 10)
    runner, client, _, _, playback = voice_runner(capture=capture)
    assert runner.run(once=True) == 0
    assert capture.closed and not client.requests and not playback


def test_voice_model_unavailable_does_not_start_capture():
    capture = Capture([])
    runner, client, _, _, _ = voice_runner(capture=capture)
    client.tasks['audio.transcribe']['available'] = False
    assert runner.run(once=True) == 2
    assert not capture.entered and client.closed


def test_stop_closes_active_capture():
    capture = Capture([])
    runner, _, _, _, _ = voice_runner(capture=capture)
    runner.capture = capture
    runner.stop()
    assert capture.closed


def test_unselected_tasks_fail_without_loading_or_capture():
    selected = selection()
    selected['tasks'] = ['text.respond']
    capture = Capture([])
    runner, _, _, statuses, _ = voice_runner(selected=selected, capture=capture)
    assert runner.run(once=True) == 2
    assert not capture.entered
    assert any(status.get('error') == 'compute_task_not_selected' for status in statuses)


def test_playback_stop_cancels_existing_player_handle(monkeypatch):
    from apps.voice.audio import playback as module

    stop = threading.Event()
    terminated = threading.Event()
    process = SimpleNamespace(terminate=terminated.set, wait=lambda **_: terminated.wait(1), kill=terminated.set)

    class Stream:
        def __init__(self):
            self.process = process
            self.closed = False

        def write(self, _):
            stop.set()
            assert terminated.wait(1)

        def close(self, **_):
            self.closed = True
            return True, None, None

    stream = Stream()
    monkeypatch.setattr(module, 'start_stream', lambda *a, **k: stream)
    logger = SimpleNamespace(event=lambda *a, **k: None)
    assert module.play_bytes(b'audio', 'wav', module.PlaybackConfig(), logger, stop_event=stop) is False
    assert terminated.is_set() and stream.closed


def test_already_stopped_playback_does_not_open_player(monkeypatch):
    from apps.voice.audio import playback as module

    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(module, 'start_stream', lambda *a, **k: pytest.fail('player opened after OFF'))
    assert module.play_bytes(b'audio', 'wav', module.PlaybackConfig(), stop_event=stop) is False


@pytest.mark.parametrize('entry,once', [('run_listen', False), ('run_once', True)])
def test_voice_entry_prefers_selected_compute_without_legacy_fallback(monkeypatch, entry, once):
    from apps.compute import __main__ as cli
    from apps.voice import svc_core
    from services import compute_config

    selected = selection()
    calls = []
    monkeypatch.setattr(compute_config, 'selected_executor', lambda: selected)
    monkeypatch.setattr(cli, 'run_goal', lambda *a, **k: calls.append((a, k)) or 17)
    monkeypatch.setattr(svc_core, 'should_offload_to_pc', lambda: pytest.fail('legacy PC mode entered'))
    monkeypatch.setattr(svc_core, '_wants_stream', lambda *a: pytest.fail('local provider entered'))
    cfg = {'lang': 'pl'}
    assert getattr(svc_core, entry)(cfg, object()) == 17
    assert calls[0][0] == ('voice', cfg)
    assert calls[0][1].get('once', False) is once


def test_vision_entry_does_not_create_legacy_camera_or_obstacle_bridge(monkeypatch):
    from apps.compute import __main__ as cli
    from apps.vision import offload_dispatcher
    from services import compute_config

    selected = selection()
    monkeypatch.setattr(compute_config, 'selected_executor', lambda: selected)
    monkeypatch.setattr(cli, 'run_goal', lambda domain, **k: 19 if domain == 'vision' else 1)
    monkeypatch.setattr(offload_dispatcher, 'VisionOffloadDispatcher', lambda: pytest.fail('legacy camera opened'))
    monkeypatch.setattr(offload_dispatcher, 'EnhancedObstacleBridge', lambda: pytest.fail('obstacle bridge opened'))
    assert offload_dispatcher.main() == 19


def test_heartbeat_is_bounded_and_status_has_source_metrics():
    runner, _, _, _, statuses = vision_runner([])
    now = [0.0]
    runner.clock = lambda: now[0]
    for _ in range(50):
        runner._heartbeat('listening')
    assert len(statuses) == 1
    now[0] = 5.0
    runner._heartbeat('listening')
    assert len(statuses) == 2
    runner.emit(
        {
            'task': 'vision.describe',
            'captured_at': 990,
            'metrics': {'source_age_ms': 10000},
            'data': {'text': 'scene'},
            'quality': {'simulated': True},
        }
    )
    assert statuses[-1]['captured_at'] == 990
    assert statuses[-1]['metrics']['source_age_ms'] == 10000
    runner.close()


def test_cli_text_uses_same_client_and_does_not_start_media(monkeypatch, capsys):
    from apps.compute import __main__ as cli

    client = Client()
    client.__class__ = type(
        'ManagedClient',
        (Client,),
        {
            '__enter__': lambda self: self,
            '__exit__': lambda self, *_: self.close(),
        },
    )
    monkeypatch.setattr(cli, 'selected_executor', selection)
    monkeypatch.setattr(cli, 'ComputeClient', lambda *a, **k: client)
    monkeypatch.setattr(cli, 'run_goal', lambda *a, **k: pytest.fail('media started for text'))
    assert cli.main(['text', '--text', 'cześć']) == 0
    assert client.requests[0][0] == 'text.respond'
    assert 'test-token' not in capsys.readouterr().out
    assert client.closed


@pytest.mark.parametrize('data,mime', [(b'\xff\xd8\xffjpeg', 'image/jpeg'), (b'\x89PNG\r\n\x1a\npng', 'image/png')])
def test_frame_source_preserves_encoded_bytes_and_marks_file_time(monkeypatch, data, mime):
    from common import frame_stream

    options = []
    stream = SimpleNamespace(recv=lambda _: data, metadata={'mtime': 998, 'id': 4}, close=lambda: None)
    monkeypatch.setattr(frame_stream, 'FrameStreamClient', lambda *a, **k: options.append(k) or stream)
    source = FrameSource()
    assert source.recv(1) == {
        'data': data,
        'captured_at': 998,
        'input_id': 'frame-4',
        'content_type': mime,
        'timestamp_source': 'file_mtime',
    }
    assert options == [{'latest': True, 'max_pending': 2, 'encoded': True}]
    source.close()


def test_frame_source_uses_actual_capture_time_without_receipt_time(monkeypatch):
    from common import frame_stream

    stream = SimpleNamespace(
        recv=lambda _: b'\xff\xd8\xffjpeg',
        metadata={'captured_at': 990, 'mtime': 999, 'ts': 1000, 'id': 4},
        close=lambda: None,
    )
    monkeypatch.setattr(frame_stream, 'FrameStreamClient', lambda *a, **k: stream)
    source = FrameSource()
    frame = source.recv(1)
    assert frame['captured_at'] == 990 and frame['timestamp_source'] == 'capture'
    stream.metadata = {'ts': 1000, 'id': 5}
    assert source.recv(1) is None
    source.close()


def test_model_status_is_distinct_from_available_and_health_not_audio_silence():
    runner, client, _, statuses, _ = voice_runner(transcript='')
    now = [0.0]
    runner.clock = lambda: now[0]
    runner._start({'audio.transcribe', 'text.respond', 'audio.synthesize'})
    assert statuses[-1]['state'] == 'waiting_for_input'
    assert statuses[-1]['capabilities']['tasks']['audio.transcribe']['ready'] is False
    assert client.capability_calls == 1
    for _ in range(50):
        runner._health()
    assert client.capability_calls == 1
    now[0] = 10
    runner.capture = object()
    runner._health()
    assert client.capability_calls == 1  # No network stall during microphone reads.
    runner.capture = None
    runner._health()
    assert client.capability_calls == 2
    runner.close()


@pytest.mark.parametrize('enabled,allowed', [(False, True), (True, False), (True, True)])
def test_conversation_task_requires_selected_allowlist_and_actual_capability(enabled, allowed):
    selected = selection()
    if allowed:
        selected['tasks'] = [*TASKS, 'conversation.respond']
    runner, client, _, _, playback = voice_runner(selected=selected)
    client.tasks['conversation.respond'] = {'available': enabled}
    try:
        runner._start({'audio.transcribe', 'text.respond', 'audio.synthesize'})
        expected = 'conversation.respond' if enabled and allowed else 'text.respond'
        assert runner.response_task() == expected
        runner.process(wav_bytes(b'\0\0' * 320, 16000), 999)
        assert client.requests[1][0] == expected
        assert client.requests[-1][0] == 'audio.synthesize' and playback
    finally:
        runner.close()


def test_conversation_already_spoken_reply_is_not_synthesised_or_played_again():
    selected = selection()
    selected['tasks'] = [*TASKS, 'conversation.respond']
    runner, client, _, _, playback = voice_runner(selected=selected)
    client.tasks['conversation.respond'] = {'available': True}
    original = client.result

    def result(job, **kwargs):
        observed = original(job, **kwargs)
        if observed['task'] == 'conversation.respond':
            observed['data']['speech_played'] = True
        return observed

    client.result = result
    try:
        runner._start({'audio.transcribe', 'text.respond', 'audio.synthesize'})
        reply = runner.process(wav_bytes(b'\0\0' * 320, 16000), 999)
        assert reply['data']['speech_played'] is True
        assert [request[0] for request in client.requests] == ['audio.transcribe', 'conversation.respond']
        assert not playback
    finally:
        runner.close()


@pytest.mark.parametrize('domain', ['voice', 'vision'])
def test_goal_signal_marks_stop_then_finally_closes_outside_http_lock(monkeypatch, domain):
    from apps.compute import __main__ as cli
    from common import bus

    callbacks, restored, events = {}, [], []
    lock = threading.Lock()
    publisher = Publisher()
    previous = {signum: object() for signum in (cli.signal.SIGINT, cli.signal.SIGTERM)}

    class Runner:
        def __init__(self, *_, **__):
            self.stop_event = threading.Event()

        def run(self, **_):
            with lock:
                callbacks[cli.signal.SIGTERM](cli.signal.SIGTERM, None)
                assert self.stop_event.is_set()
                assert not events  # No close/cancel in the signal handler.
            return 17

        def stop(self):
            pytest.fail('signal called synchronous runner.stop')

        def close(self):
            assert lock.acquire(blocking=False), 'close re-entered the held HTTP lock'
            lock.release()
            events.append('finally-close')
            publisher.close()

    def register(signum, handler):
        if handler is previous[signum]:
            restored.append(signum)
        else:
            callbacks[signum] = handler

    monkeypatch.setattr(bus, 'BusPub', lambda: publisher)
    monkeypatch.setattr(cli, 'VoiceRunner', Runner)
    monkeypatch.setattr(cli, 'VisionRunner', Runner)
    monkeypatch.setattr(cli.signal, 'getsignal', lambda signum: previous[signum])
    monkeypatch.setattr(cli.signal, 'signal', register)
    assert cli.run_goal(domain, selection=selection()) == 17
    assert events == ['finally-close'] and publisher.closed
    assert restored == [cli.signal.SIGINT, cli.signal.SIGTERM]
