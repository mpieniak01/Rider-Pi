"""Streaming voice failure ownership without audio devices or worker threads."""

import queue
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.voice import svc_audio
from apps.voice.audio import playback
from apps.voice.stream.playout import StreamPlayoutMixin


@pytest.fixture
def service():
    instance = StreamPlayoutMixin()
    instance.logger = Mock()
    instance._playback_cfg = object()
    instance._capture_cfg_dict = {}
    instance.ptt_state = SimpleNamespace(transition=Mock())
    instance.stop_event = threading.Event()
    instance.barge_in_event = threading.Event()
    instance.audio_queue = queue.Queue()
    instance.tts_player_queue = queue.Queue()
    instance._capture_thread = None
    instance._tts_player_thread = None
    return instance


@pytest.mark.parametrize("close_fails", [False, True])
def test_opened_playback_is_closed_if_state_transition_fails(service, monkeypatch, close_fails):
    stream = SimpleNamespace(close=Mock(side_effect=OSError("close failed") if close_fails else None))
    monkeypatch.setattr(playback, "start_stream", lambda *_args: stream)
    service.ptt_state.transition.side_effect = ValueError("state callback failed")
    assert service._start_tts_stream() is None
    stream.close.assert_called_once()
    service.logger.event.assert_called_once_with("tts.stream.start_error", error="state callback failed")


def test_failed_playback_open_has_no_owned_resource_to_close(service, monkeypatch):
    open_stream = Mock(side_effect=OSError("device unavailable"))
    monkeypatch.setattr(playback, "start_stream", open_stream)
    service._close_tts_stream = Mock()
    assert service._start_tts_stream() is None
    service._close_tts_stream.assert_called_once_with(None)
    service.ptt_state.transition.assert_not_called()


@pytest.mark.parametrize("write_fails,close_fails", [(False, False), (True, False), (True, True)])
def test_playback_write_failure_relinquishes_owned_stream(service, write_fails, close_fails):
    stream = SimpleNamespace(
        write=Mock(side_effect=OSError("write failed") if write_fails else None),
        close=Mock(side_effect=OSError("close failed") if close_fails else None),
    )
    result = service._write_tts_chunk(stream, b"pcm")
    stream.write.assert_called_once_with(b"pcm")
    if write_fails:
        assert result is None
        stream.close.assert_called_once()
        service.logger.event.assert_called_once_with("tts.stream.write_error", error="write failed")
    else:
        assert result is stream
        stream.close.assert_not_called()


def test_playback_end_marker_logs_close_failure_and_drops_reference(service):
    stream = SimpleNamespace(close=Mock(side_effect=OSError("close failed")))
    assert service._write_tts_chunk(stream, None) is None
    service.logger.event.assert_called_once_with("tts.stream.close_error", error="close failed")


@pytest.mark.parametrize("capture_fails", [False, True])
def test_capture_barge_in_discards_old_tts_and_always_sends_end_marker(service, monkeypatch, capture_fails):
    service.tts_player_queue.put(b"old tts")
    service.barge_in_event.set()

    def frames(_config, chunk_size):
        assert chunk_size == 20
        yield b"first"
        if capture_fails:
            raise OSError("capture failed")
        yield b"second"

    monkeypatch.setattr(svc_audio, "capture_continuous", frames)
    service._capture_worker(20)
    expected = [b"first", None] if capture_fails else [b"first", b"second", None]
    assert [service.audio_queue.get_nowait() for _ in expected] == expected
    assert service.audio_queue.empty()
    assert service.tts_player_queue.empty()
    assert not service.barge_in_event.is_set()
    if capture_fails:
        service.logger.event.assert_called_once_with("capture_thread_error", error="capture failed")


def test_capture_stop_never_queues_another_frame(service, monkeypatch):
    monkeypatch.setattr(svc_audio, "capture_continuous", lambda *_args: iter([b"late"]))
    service.stop_event.set()
    service._capture_worker(20)
    assert service.audio_queue.get_nowait() is None
    assert service.audio_queue.empty()


def test_cleanup_failures_still_clear_thread_references(service):
    bad_queue = Mock(put_nowait=Mock(side_effect=OSError("queue closed")))
    bad_thread = SimpleNamespace(is_alive=lambda: True, join=Mock(side_effect=RuntimeError("join failed")))
    service.audio_queue = bad_queue
    service._capture_thread = bad_thread
    service._tts_player_thread = bad_thread
    service._cleanup_workers()
    assert service.stop_event.is_set()
    assert service._capture_thread is None
    assert service._tts_player_thread is None
    assert service.tts_player_queue.get_nowait() is None
    assert bad_thread.join.call_count == 2
