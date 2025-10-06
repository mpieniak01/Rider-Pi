"""Unit tests for WebSocket close handling in voice streaming."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from apps.voice.svc_stream import StreamingVoiceService


class TestWebSocketClose:
    """Test graceful WebSocket closure."""

    @pytest.fixture
    def mock_websocket(self):
        """Create a mock WebSocket with close and wait_closed methods."""
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()
        mock_ws.wait_closed = AsyncMock()
        return mock_ws

    @pytest_asyncio.fixture
    async def service(self):
        """Create a streaming service for testing."""
        config = {
            "stream": {"endpoint": "ws://test", "auth": "test-key"},
            "capture": {"sample_rate": 16000, "channels": 2},
            "playback": {},
            "service": {"beep": False},
        }
        svc = StreamingVoiceService(config)
        yield svc
        # Proper cleanup - await close to prevent unawaited coroutine warning
        try:
            await svc.close()
        except Exception:
            pass

    @pytest.mark.asyncio
    async def test_close_with_valid_websocket(self, service, mock_websocket):
        """Test normal WebSocket closure."""
        service.websocket = mock_websocket
        service.connected = True
        service.session_id = "test-session"

        await service.close()

        # Should call close with code 1000 and wait for closure
        mock_websocket.close.assert_called_once_with(code=1000)
        mock_websocket.wait_closed.assert_called_once()

        # Should clean up state
        assert service.websocket is None
        assert not service.connected

    @pytest.mark.asyncio
    async def test_close_with_no_websocket(self, service):
        """Test close when no WebSocket is present."""
        service.websocket = None

        # Should not raise exception
        await service.close()

        assert service.websocket is None

    @pytest.mark.asyncio
    async def test_close_with_exception(self, service, mock_websocket):
        """Test close handling when WebSocket operations fail."""
        service.websocket = mock_websocket
        service.connected = True
        service.session_id = "test-session"

        # Make close() raise an exception
        mock_websocket.close.side_effect = Exception("Connection error")

        # Should not raise exception, should log error
        await service.close()

        # Should still clean up state
        assert service.websocket is None
        assert not service.connected

    @pytest.mark.asyncio
    async def test_close_wait_closed_exception(self, service, mock_websocket):
        """Test close handling when wait_closed fails."""
        service.websocket = mock_websocket
        service.connected = True
        service.session_id = "test-session"

        # Make wait_closed() raise an exception
        mock_websocket.wait_closed.side_effect = Exception("Wait failed")

        # Should not raise exception
        await service.close()

        # Should still clean up
        assert service.websocket is None
        assert not service.connected

        # Should have called both methods
        mock_websocket.close.assert_called_once_with(code=1000)
        mock_websocket.wait_closed.assert_called_once()


class TestServiceStop:
    """Test service stop and cleanup."""

    @pytest_asyncio.fixture
    async def service(self):
        """Create a streaming service for testing."""
        config = {
            "stream": {"endpoint": "ws://test", "auth": "test-key"},
            "capture": {"sample_rate": 16000, "channels": 2},
            "playback": {},
            "service": {"beep": False},
        }
        svc = StreamingVoiceService(config)
        yield svc
        # Proper cleanup - await close to prevent unawaited coroutine warning
        try:
            await svc.close()
        except Exception:
            pass

    @pytest.mark.asyncio
    async def test_stop_sets_flags(self, service):
        """Test that stop() sets appropriate flags."""
        service.stop()

        assert service.stop_event.is_set()
        assert not service.connected

    @pytest.mark.asyncio
    async def test_stop_with_running_loop(self, service):
        """Test stop with event loop (scheduling close)."""
        mock_loop = MagicMock()
        # Make is_running return True to trigger async path
        mock_loop.is_running.return_value = True
        service._loop = mock_loop
        service.websocket = MagicMock()

        # Mock asyncio.run_coroutine_threadsafe to actually run the coroutine
        # This prevents "unawaited coroutine" warnings
        with patch('asyncio.run_coroutine_threadsafe') as mock_schedule:
            # Create a mock future that can be awaited
            mock_future = MagicMock()
            
            # Make the mock actually await the coroutine to prevent warnings
            async def run_coro(coro, loop):
                try:
                    await coro
                except Exception:
                    pass
                return mock_future
            
            # Replace with async version
            mock_schedule.side_effect = lambda coro, loop: asyncio.create_task(run_coro(coro, loop))
            
            service.stop()

            # Should attempt to schedule close
            mock_schedule.assert_called_once()
