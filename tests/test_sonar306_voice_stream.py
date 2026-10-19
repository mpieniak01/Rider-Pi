"""Stream packet boundary contracts; all sockets, audio and clocks are inert fakes."""

from __future__ import annotations

import asyncio
import base64
import json
import queue
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest

from apps.voice import svc_audio
from apps.voice.stream import transport as transport_module
from apps.voice.stream.handlers import StreamHandlersMixin
from apps.voice.stream.playout import StreamPlayoutMixin
from apps.voice.stream.state import PTTEvent, PTTState, PTTStateMachine
from apps.voice.stream.svc_streaming import StreamingVoiceService


@pytest.mark.parametrize("state", list(PTTState))
@pytest.mark.parametrize("event", list(PTTEvent))
def test_ptt_global_events_and_terminal_states_keep_priority(state, event):
    fsm = PTTStateMachine(logger=Mock())
    if event == PTTEvent.ERROR:
        assert fsm._next_state(state, event) == PTTState.ERROR
    elif event == PTTEvent.CANCEL or state == PTTState.CLOSING:
        assert fsm._next_state(state, event) == PTTState.IDLE
    elif event == PTTEvent.VOICE_START:
        assert fsm._next_state(state, event) == state
    else:
        assert isinstance(fsm._next_state(state, event), PTTState)


@pytest.fixture
def handler():
    instance = StreamHandlersMixin()
    instance.logger = Mock()
    instance.ptt_state = Mock()
    instance.tts_player_queue = queue.Queue()
    instance._bw_rx_total = 0
    instance._completed = False
    instance._publish_partial = Mock()
    instance._publish_error = Mock()
    instance._commit_audio_buffer = AsyncMock()
    instance._session_tasks = Mock()
    instance._handle_transcript = Mock(return_value="inert-task")
    return instance


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["response.audio.delta", "response.output_audio.delta"])
async def test_audio_delta_preserves_bytes_and_bandwidth(handler, kind):
    await handler._handle_message(json.dumps({"type": kind, "delta": base64.b64encode(b"pcm").decode()}))
    assert handler.tts_player_queue.get_nowait() == b"pcm"
    assert handler._bw_rx_total == 3
    await handler._handle_message(json.dumps({"type": kind, "delta": "a"}))
    assert handler.tts_player_queue.empty()
    assert handler.logger.event.call_args.args[0] == "audio.delta.b64_error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,event",
    [
        ("response.created", PTTEvent.SERVER_RESPONSE),
        ("input_audio_buffer.speech_started", PTTEvent.VOICE_START),
        ("input_audio_buffer.speech_stopped", PTTEvent.VOICE_END),
        ("response.done", PTTEvent.TTS_COMPLETE),
        ("response.audio.done", PTTEvent.TTS_COMPLETE),
        ("error", PTTEvent.ERROR),
    ],
)
async def test_server_event_dispatch_retains_transitions_and_commit(handler, kind, event):
    await handler._handle_message(json.dumps({"type": kind}))
    handler.ptt_state.transition.assert_called_once_with(event)
    assert handler._commit_audio_buffer.await_count == (kind == "input_audio_buffer.speech_stopped")
    assert handler._completed == (kind == "response.done")


@pytest.mark.asyncio
async def test_transcription_dispatch_trims_task_input_and_ignores_empty(handler):
    for transcript in ["  hello  ", "   "]:
        await handler._handle_message(
            json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": transcript})
        )
    handler._handle_transcript.assert_called_once_with("hello")
    handler._session_tasks.create.assert_called_once_with("inert-task", name="voice-transcript")
    await handler._handle_message("malformed")
    assert handler.logger.event.call_args.args[0] == "message_parse_error"


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback_async", [False, True])
async def test_legacy_ui_events_and_fallback_accept_both_handler_kinds(handler, fallback_async):
    handler.ui_publisher = Mock()
    fallback = AsyncMock() if fallback_async else Mock()
    handler._handle_message = fallback
    await handler._handle_ws_message('{"type":"input_audio_buffer.speech_started"}')
    handler.ui_publisher.publish.assert_called_once_with("ui.state", {"state": "hearing"})
    await handler._handle_ws_message("invalid")
    fallback.assert_called_once_with("invalid")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "idle,elapsed,expected", [(0.199, 0.999, None), (0.2, 0.5, "silence"), (0.1, 1.0, "maxturn"), (0.2, 1.0, "silence")]
)
async def test_commit_timer_boundary_and_silence_priority(idle, elapsed, expected):
    service = object.__new__(StreamingVoiceService)
    service._any_audio_since_commit = True
    service._last_audio_ts = -idle
    service._last_commit_ts = -elapsed
    service.logger = Mock()
    service._commit_audio_buffer = AsyncMock()
    await service._commit_audio_on_timer(0, 0.2, 1)
    if expected:
        assert service._commit_audio_buffer.await_count == 1
        assert service.logger.event.call_args.args[0] == "audio.commit.timer_" + expected
    else:
        service._commit_audio_buffer.assert_not_awaited()


@pytest.mark.parametrize("write_error", [False, True])
def test_player_write_failures_close_and_next_chunk_restarts(monkeypatch, write_error):
    from apps.voice.audio import playback

    player = StreamPlayoutMixin()
    player.logger = Mock()
    player._playback_cfg = object()
    player.ptt_state = Mock()
    stream = Mock()
    if write_error:
        stream.write.side_effect = OSError("write failed")
    start = Mock(return_value=stream)
    monkeypatch.setattr(playback, "start_stream", start)
    result = player._write_tts_chunk(None, b"chunk")
    stream.write.assert_called_once_with(b"chunk")
    player.ptt_state.transition.assert_called_once_with(PTTEvent.TTS_START)
    assert result is (None if write_error else stream)
    if not write_error:
        assert player._write_tts_chunk(result, None) is None
    stream.close.assert_called_once()


def test_capture_barge_in_drains_output_and_always_signals_end(monkeypatch):
    worker = StreamPlayoutMixin()
    worker.logger = Mock()
    worker._capture_cfg_dict = {"backend": "fake"}
    worker.stop_event = threading.Event()
    worker.barge_in_event = threading.Event()
    worker.barge_in_event.set()
    worker.audio_queue = queue.Queue()
    worker.tts_player_queue = queue.Queue()
    worker.tts_player_queue.put(b"stale")
    capture = Mock(return_value=iter([b"first", b"second"]))
    monkeypatch.setattr(svc_audio, "capture_continuous", capture)
    worker._capture_worker(32)
    assert list(worker.audio_queue.queue) == [b"first", b"second", None]
    assert worker.tts_player_queue.empty() and not worker.barge_in_event.is_set()
    capture.assert_called_once_with({"backend": "fake"}, 32)


@pytest.mark.asyncio
@pytest.mark.parametrize("async_library", [False, True])
async def test_transport_library_headers_are_retained_without_network(monkeypatch, async_library):
    instance = transport_module.WebSocketTransport("ws://fake.invalid", "Bearer fake", logger=Mock())
    instance._use_async = async_library
    instance._heartbeat_loop = AsyncMock()
    socket = Mock()
    async_connect = AsyncMock(return_value=socket)
    sync_connect = Mock(return_value=socket)
    monkeypatch.setattr(transport_module, "_ws_async", SimpleNamespace(connect=async_connect))
    monkeypatch.setattr(transport_module, "_ws_sync", SimpleNamespace(create_connection=sync_connect))
    monkeypatch.delenv("OPENAI_REALTIME_ENDPOINT", raising=False)
    assert await instance.connect(max_retries=0)
    assert instance.connected and instance.websocket is socket
    if async_library:
        headers = async_connect.call_args.kwargs["extra_headers"]
        assert headers == [("Authorization", "Bearer fake"), ("OpenAI-Beta", "realtime=v1")]
    else:
        assert sync_connect.call_args.kwargs["header"] == ["Authorization: Bearer fake", "OpenAI-Beta: realtime=v1"]
    await instance._heartbeat_task


@pytest.mark.asyncio
async def test_transport_connect_retries_with_existing_backoff(monkeypatch):
    instance = transport_module.WebSocketTransport("ws://fake.invalid", "", logger=Mock())
    instance._connect_websocket = AsyncMock(side_effect=OSError("offline"))
    sleep = AsyncMock()
    monkeypatch.setattr(transport_module, "asyncio", SimpleNamespace(sleep=sleep))
    monkeypatch.delenv("OPENAI_REALTIME_ENDPOINT", raising=False)
    assert not await instance.connect(max_retries=2)
    assert instance._connect_websocket.await_count == 3
    assert sleep.await_args_list == [call(1), call(2)]


def test_error_timestamp_retains_utc_z_format():
    service = object.__new__(StreamingVoiceService)
    service.ui_publisher = Mock()
    service._publish_error("fake", "error")
    timestamp = service.ui_publisher.publish.call_args.args[1]["ts"]
    from datetime import datetime, timezone

    assert timestamp.endswith("Z") and "+00:00" not in timestamp
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    assert parsed.tzinfo == timezone.utc
