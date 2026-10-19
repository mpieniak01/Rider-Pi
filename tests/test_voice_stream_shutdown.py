"""Actual voice orchestration on fake transports/workers; no robot/provider I/O."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio

from apps.voice.stream.svc_streaming import StreamingVoiceService


@pytest_asyncio.fixture
async def service():
    """Build only configuration and replace all device/network worker entry points."""
    instance = StreamingVoiceService({})
    instance.logger = Mock()
    instance._session_tasks.logger = instance.logger
    instance.transport = AsyncMock()
    instance._start_audio_capture = Mock()
    instance._start_tts_player = Mock()
    instance._cleanup_workers = Mock()
    instance._publish_ui_state = Mock()
    instance.ptt_state = Mock()
    instance._send_session_init = AsyncMock()
    yield instance
    await instance.close()


@pytest.mark.asyncio
async def test_transcript_task_is_owned_and_stopped_before_transport_closes(service):
    """An active transcript cannot outlive its session transport."""
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def transcript(_text):
        started.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    service._handle_transcript = transcript
    await service._handle_message(
        json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": "hello"})
    )
    await started.wait()
    tasks = tuple(service._session_tasks.tasks)
    assert len(tasks) == 1

    async def close_transport():
        assert stopped.is_set()

    service.transport.close.side_effect = close_transport
    await service.close()
    assert tasks[0].cancelled()
    assert not service._session_tasks.tasks
    assert service.transport is None


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_worker", [False, True])
async def test_session_owns_watchdog_and_drains_it_on_every_exit(service, terminal_worker):
    """Both cancellation and worker termination end the RX watchdog lifetime."""
    started = asyncio.Event()

    async def messages():
        started.set()
        if not terminal_worker:
            await asyncio.Future()

    service._message_handler_loop = messages
    service._audio_sender_loop = AsyncMock(side_effect=lambda: None) if terminal_worker else waiting
    service.ptt_enabled = False
    session = asyncio.create_task(service._run_session())
    await started.wait()
    tasks = tuple(service._session_tasks.tasks)
    watchdog = next(task for task in tasks if task.get_name() == "voice-rx-watchdog")
    if terminal_worker:
        await asyncio.wait_for(session, timeout=2)
    else:
        session.cancel()
        with pytest.raises(asyncio.CancelledError):
            await session
    assert watchdog.cancelled()
    assert all(task.done() for task in tasks)
    assert not service._session_tasks.tasks
    assert service._audio_sender_task is None
    assert service._message_handler_task is None


async def waiting():
    """A cancellable worker which never touches a real stream."""
    await asyncio.Future()


@pytest.mark.asyncio
async def test_audio_sender_empty_queue_does_not_starve_cancellation(service):
    """Polling an empty audio queue yields to the event loop and remains cancellable."""
    task = asyncio.create_task(service._audio_sender_loop())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    service.logger.event.assert_any_call("audio.sender.stop")


@pytest.mark.asyncio
async def test_keyboard_worker_propagates_cancellation_and_logs_stop(service, monkeypatch):
    """No stdin thread is launched; the pending executor future is cancelled."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    monkeypatch.setattr(loop, "run_in_executor", Mock(return_value=future))
    task = asyncio.create_task(service._keyboard_ptt_loop())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    service.logger.event.assert_any_call("ptt.keyboard.stop")


@pytest.mark.asyncio
async def test_parent_cancel_during_cleanup_still_closes_resources(service):
    """Cancelling cleanup cannot silently become a successful close or skip resources."""
    started = asyncio.Event()
    cleaning = asyncio.Event()

    async def child():
        started.set()
        try:
            await asyncio.Future()
        finally:
            cleaning.set()
            await asyncio.Future()

    service._session_tasks.create(child(), name="pending")
    await started.wait()
    transport = service.transport
    parent = asyncio.create_task(service.close())
    await cleaning.wait()
    parent.cancel()
    with pytest.raises(asyncio.CancelledError):
        await parent
    transport.close.assert_awaited_once()
    service._cleanup_workers.assert_called_once()
    assert not service.connected
    assert service.transport is None


@pytest.mark.asyncio
async def test_transport_close_cancellation_still_closes_legacy_socket(service):
    """A cancelled first close cannot skip a second legacy socket or local workers."""
    transport = service.transport
    transport.close.side_effect = asyncio.CancelledError
    socket = AsyncMock()
    service.websocket = socket
    service.connected = True
    with pytest.raises(asyncio.CancelledError):
        await service.close()
    socket.close.assert_awaited_once_with(code=1000)
    service._cleanup_workers.assert_called_once()
    assert service.websocket is None
    assert not service.connected


@pytest.mark.asyncio
async def test_listen_cancellation_awaits_cleanup_without_calling_blocking_stop(service):
    """The async listener never waits synchronously on its own event loop."""
    started = asyncio.Event()

    async def session():
        started.set()
        await asyncio.Future()

    service._initialize_transport = AsyncMock(return_value=True)
    service._run_with_reconnect = session
    service.stop = Mock(side_effect=AssertionError("sync stop must not run on event loop"))
    transport = service.transport
    listener = asyncio.create_task(service.listen())
    await started.wait()
    listener.cancel()
    with pytest.raises(asyncio.CancelledError):
        await listener
    service.stop.assert_not_called()
    transport.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_close_serializes_transport_shutdown(service):
    """Two callers share resource ownership rather than closing the socket twice."""
    started = asyncio.Event()
    release = asyncio.Event()
    transport = service.transport

    async def slow_close():
        started.set()
        await release.wait()

    transport.close.side_effect = slow_close
    first = asyncio.create_task(service.close())
    await started.wait()
    second = asyncio.create_task(service.close())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)
    transport.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_ptt_idle_callbacks_are_owned_and_rejected_after_close(service):
    """Thread-safe PTT callbacks cannot run an unowned state change after shutdown."""
    service._loop = asyncio.get_running_loop()
    service._transition_to_idle = AsyncMock(side_effect=waiting)
    service._on_closing()
    await asyncio.sleep(0)
    tasks = tuple(service._session_tasks.tasks)
    assert len(tasks) == 1
    assert tasks[0].get_name() == "voice-idle"
    await service.close()
    assert tasks[0].cancelled()
    service._on_closing()
    await asyncio.sleep(0)
    assert not service._session_tasks.tasks


@pytest.mark.asyncio
async def test_close_failure_still_resets_state_and_worker_resources(service):
    """Ordinary socket errors are logged while all local cleanup still executes."""
    service.transport.close.side_effect = RuntimeError("transport close failed")
    service.websocket = AsyncMock()
    service.websocket.close.side_effect = RuntimeError("legacy close failed")
    service.connected = True
    await service.close()
    assert service.transport is None
    assert service.websocket is None
    assert not service.connected
    service._cleanup_workers.assert_called_once()
    service.ptt_state.reset.assert_called_once()


@pytest.mark.asyncio
async def test_once_cancellation_drains_workers_before_returning(service):
    """Single-turn cancellation follows the same owned cleanup path as listening."""
    started = asyncio.Event()

    async def completion():
        started.set()
        await asyncio.Future()

    service._initialize_transport = AsyncMock(return_value=True)
    service._wait_for_completion = completion
    service._message_handler_loop = waiting
    service._audio_sender_loop = waiting
    task = asyncio.create_task(service.once())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not service._session_tasks.tasks
    service._cleanup_workers.assert_called_once()
