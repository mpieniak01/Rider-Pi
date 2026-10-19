"""WebSocket cancellation boundaries using in-memory fakes only."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from apps.voice.stream.transport import ReconnectingTransport, WebSocketTransport


def transport_fixture():
    """Construct transport configuration without connecting to any endpoint."""
    instance = WebSocketTransport("ws://localhost.invalid/voice", "", logger=Mock())
    instance._use_async = True
    instance.websocket = AsyncMock()
    instance.websocket.closed = False
    instance.connected = True
    return instance


@pytest.mark.asyncio
async def test_heartbeat_cancellation_is_not_reported_as_success():
    """An explicitly cancelled heartbeat must retain its cancelled outcome."""
    transport = transport_fixture()
    transport.ping_interval_s = 60
    task = asyncio.create_task(transport._heartbeat_loop())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await transport.close()


@pytest.mark.asyncio
async def test_close_releases_socket_even_after_connection_was_marked_failed():
    """Failure of recv/heartbeat does not remove ownership of the underlying socket."""
    transport = transport_fixture()
    socket = transport.websocket
    transport.connected = False
    await transport.close()
    socket.close.assert_awaited_once_with(code=1000)
    socket.wait_closed.assert_awaited_once()
    assert transport.websocket is None
    await transport.close()
    socket.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_consumes_child_cancellation_and_clears_heartbeat_reference():
    """Normal close cancels and drains its heartbeat before closing the socket."""
    transport = transport_fixture()
    child = asyncio.create_task(asyncio.sleep(60))
    transport._heartbeat_task = child
    socket = transport.websocket
    await transport.close()
    assert child.cancelled()
    assert transport._heartbeat_task is None
    socket.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelling_close_parent_propagates_after_socket_cleanup():
    """Parent cancellation during heartbeat draining still closes its socket."""
    transport = transport_fixture()
    started = asyncio.Event()
    cleaning = asyncio.Event()

    async def child():
        started.set()
        try:
            await asyncio.Future()
        finally:
            cleaning.set()
            await asyncio.Future()

    transport._heartbeat_task = asyncio.create_task(child())
    await started.wait()
    socket = transport.websocket
    parent = asyncio.create_task(transport.close())
    await cleaning.wait()
    parent.cancel()
    with pytest.raises(asyncio.CancelledError):
        await parent
    socket.close.assert_awaited_once()
    assert transport._heartbeat_task is None
    assert not transport.connected


@pytest.mark.asyncio
async def test_reconnecting_close_clears_reference_even_on_cancellation():
    """An aborted close must not leave a stale reconnect wrapper marked live."""
    transport = ReconnectingTransport("ws://localhost.invalid/voice", "", logger=Mock())
    transport.transport = AsyncMock()
    transport.transport.close.side_effect = asyncio.CancelledError
    transport.retry_count = 2
    with pytest.raises(asyncio.CancelledError):
        await transport.close()
    assert transport.transport is None
    assert transport.retry_count == 0


@pytest.mark.asyncio
async def test_sync_socket_close_uses_executor_and_clears_state():
    """The sync-library branch closes the existing socket without network calls."""
    transport = transport_fixture()
    transport._use_async = False
    socket = Mock()
    transport.websocket = socket
    await transport.close()
    socket.close.assert_called_once_with(status=1000)
    assert transport.websocket is None


@pytest.mark.asyncio
async def test_socket_close_failure_is_reported_without_stale_state():
    """A failed close cannot leave the transport advertising a live connection."""
    transport = transport_fixture()
    transport.websocket.close.side_effect = RuntimeError("socket close failed")
    await transport.close()
    transport.logger.event.assert_any_call("ws.close_error", error="socket close failed")
    assert transport.websocket is None
    assert not transport.connected
