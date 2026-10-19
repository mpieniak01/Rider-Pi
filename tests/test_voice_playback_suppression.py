"""Speaker echo is dropped before remote STT/conversation, without physical audio."""

import io
import struct
import threading
import wave
from types import SimpleNamespace

import pytest
from flask import Flask

from apps.compute.client import ComputeError
from apps.voice.audio import ownership
from services.api_core import playback_api
from services.audio_playback import PlaybackManager
from tests.test_compute_runners import Capture, selection, voice_runner, wav_bytes

VOICED = struct.pack('<h', 1000) * 320
NEXT_INPUT = struct.pack('<h', 2000) * 320
SILENT = b'\0\0' * 320


@pytest.fixture
def clock(monkeypatch, tmp_path):
    monkeypatch.setenv('RIDER_AUDIO_LOCK_PATH', str(tmp_path / 'audio.lock'))
    monkeypatch.setenv('RIDER_AGENT_TOKEN', 'unit-only-agent-token')
    now = [10.0]
    monkeypatch.setattr(ownership, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    return now


def runner_for(clock, capture):
    selected = selection()
    selected['tasks'] = [*selected['tasks'], 'conversation.respond']
    observer = ownership.PlaybackObserver(clock=lambda: clock[0])
    runner, client, publisher, statuses, _ = voice_runner(
        selected=selected, capture=capture, playback_observer=observer, clock=lambda: clock[0]
    )
    client.tasks['conversation.respond'] = {'available': True}
    runner._start({'audio.transcribe', 'text.respond', 'audio.synthesize'})
    return runner, client, publisher, statuses


def test_external_authenticated_playback_interrupts_and_drops_whole_input_then_accepts_fresh_input(clock):
    started, released = threading.Event(), threading.Event()

    def player(*_, stop_event, **__):
        with ownership.own_playback():
            started.set()
            assert stop_event.wait(2)
        released.set()
        return False

    manager = PlaybackManager(player=player, config=object(), clock=lambda: clock[0])
    app = Flask(__name__)
    playback_api.register(app, manager=manager)
    results = []

    def upload():
        with app.test_client() as http:
            results.append(
                http.post(
                    '/api/voice/playback',
                    data=wav_bytes(VOICED, 16000),
                    headers={
                        'Authorization': 'Bearer unit-only-agent-token',
                        'Content-Type': 'audio/wav',
                        'X-Rider-Playback-Id': 'external-speak',
                        'X-Rider-Playback-TTL-Ms': '5000',
                    },
                )
            )

    thread = threading.Thread(target=upload)

    def captured_frames():
        yield VOICED  # Partial real speech is also discarded after overlap.
        thread.start()
        assert started.wait(1)
        yield VOICED  # Own TTS saying "Rider do przodu" must never reach STT.
        pytest.fail('capture continued while speaker was active')

    interrupted = Capture(captured_frames())
    runner, client, publisher, statuses = runner_for(clock, interrupted)
    delegated = []
    client.result_hook = lambda task: delegated.append(task) if task == 'conversation.respond' else None
    try:
        assert runner.utterance() is None
        assert interrupted.closed
        assert runner.capture is None
        assert not client.requests
        assert not publisher.messages
        assert not delegated
        assert any(status['state'] == 'playback_suppressed' for status in statuses)
        runner.capture_factory = lambda _: pytest.fail('capture opened during playback/drain')
        assert runner.utterance() is None  # Busy playback never opens capture.
        assert manager.cancel('external-speak')['released']
        thread.join(timeout=1)
        assert not thread.is_alive()
        assert released.is_set()
        assert results[0].status_code == 409
        assert runner.utterance() is None  # Acoustic drain also keeps it closed.
        clock[0] += ownership.PLAYBACK_DRAIN_S + 0.01
        fresh = Capture([NEXT_INPUT, SILENT, SILENT])
        runner.capture_factory = lambda _: fresh
        utterance = runner.utterance()
        assert utterance is not None
        assert fresh.closed
        with wave.open(io.BytesIO(utterance[0]), 'rb') as reader:
            assert reader.readframes(reader.getnframes()) == NEXT_INPUT + SILENT + SILENT
        assert utterance[1] == pytest.approx(999.98)  # New source boundary, not refreshed old audio.
        runner.process(*utterance)
        assert [request[0] for request in client.requests] == [
            'audio.transcribe',
            'conversation.respond',
            'audio.synthesize',
        ]
        assert delegated == ['conversation.respond']
    finally:
        manager.cancel('external-speak')
        manager.close()
        if thread.ident is not None:
            thread.join(timeout=1)
        runner.close()


def test_off_closes_observer_and_never_reopens_capture(clock):
    with ownership.own_playback():
        pass
    clock[0] += ownership.PLAYBACK_DRAIN_S + 0.01
    capture = Capture([VOICED, SILENT, SILENT])
    runner, client, _, _ = runner_for(clock, capture)
    assert runner.utterance() is not None
    assert runner.playback_observer.fd is not None
    runner.stop()
    assert runner.playback_observer.fd is None
    assert capture.closed
    assert client.closed
    runner.capture_factory = lambda _: pytest.fail('capture reopened after OFF')
    with pytest.raises(ComputeError, match='compute_cancelled'):
        runner.utterance()
    assert runner.playback_observer.fd is None


@pytest.mark.parametrize('when', ['frame', 'enter', 'close'])
def test_short_playback_between_polls_or_capture_boundaries_is_not_missed(clock, when):
    def tiny_playback():
        with ownership.own_playback():
            pass
        clock[0] += 1  # Even an expired drain must not hide generation change.

    class Interrupted(Capture):
        def __enter__(self):
            if when == 'enter':
                tiny_playback()
            return super().__enter__()

        def frames(self):
            yield VOICED
            if when == 'frame':
                tiny_playback()
            yield SILENT
            yield SILENT

        def close(self):
            if when == 'close' and not self.closed:
                tiny_playback()
            super().close()

    capture = Interrupted([])
    runner, client, publisher, _ = runner_for(clock, capture)
    try:
        assert runner.utterance() is None
        assert capture.closed
        assert not client.requests
        assert not publisher.messages
    finally:
        runner.close()


def test_ownership_read_error_closes_capture_and_prevents_inference(clock):
    class Corrupt(Capture):
        def frames(self):
            yield VOICED
            ownership.lock_path().write_text('{')
            yield VOICED

    capture = Corrupt([])
    runner, client, publisher, _ = runner_for(clock, capture)
    try:
        with pytest.raises(ComputeError, match='compute_playback_state_unavailable'):
            runner.utterance()
        assert capture.closed
        assert runner.capture is None
        assert not client.requests
        assert not publisher.messages
    finally:
        runner.close()
