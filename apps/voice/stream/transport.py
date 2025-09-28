"""WebSocket transport layer for Rider-Pi voice streaming.

Provides clean WebSocket connection management with:
- Proper connection lifecycle (connect, send, recv, close)
- Heartbeat/ping handling
- Reconnection logic
- Clean shutdown with code 1000
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

from .. import voice_logging
from ..errors import StreamError

# WebSocket library handling with graceful fallback
try:
    import websockets as _websockets  # type: ignore
    websockets = _websockets
except Exception:
    class _WSStub:
        def __getattr__(self, name):
            raise ImportError("websockets library not available")
    websockets = _WSStub()  # type: ignore


class WebSocketTransport:
    """WebSocket transport with connection management and heartbeat."""

    def __init__(self, endpoint: str, auth_header: str, 
                 ping_interval_s: int = 10, logger: voice_logging.VoiceLogger | None = None):
        self.endpoint = endpoint
        self.auth_header = auth_header
        self.ping_interval_s = ping_interval_s
        self.logger = logger or voice_logging.get_logger(__name__)
        
        # Connection state
        self.websocket: Any = None
        self.session_id: str = ""
        self.connected: bool = False
        self.retry_count: int = 0
        
        # Heartbeat
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._stop_heartbeat = False

    async def connect(self, *, max_retries: int = 3) -> bool:
        """Connect to WebSocket endpoint.
        
        Args:
            max_retries: Maximum connection attempts
            
        Returns:
            True if connection successful
        """
        for attempt in range(max_retries + 1):
            try:
                # Resolve endpoint with environment variable override
                effective_endpoint = os.environ.get("OPENAI_REALTIME_ENDPOINT") or self.endpoint
                
                if not effective_endpoint:
                    self.logger.event("ws.connect.no_endpoint")
                    return False

                self.logger.event("ws.connect.attempt", 
                                endpoint=self._mask_endpoint(effective_endpoint),
                                attempt=attempt + 1)

                # Create connection
                extra_headers = {}
                if self.auth_header:
                    extra_headers["Authorization"] = self.auth_header

                self.websocket = await websockets.connect(
                    effective_endpoint,
                    extra_headers=extra_headers,
                    ping_interval=self.ping_interval_s,
                    ping_timeout=10,
                )

                self.connected = True
                self.retry_count = 0
                self.session_id = str(uuid.uuid4())
                
                # Start heartbeat
                self._stop_heartbeat = False
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                self.logger.event("ws.connected", session_id=self.session_id)
                return True

            except Exception as e:
                self.logger.event("ws.connect_failed", 
                                error=str(e), attempt=attempt + 1)
                
                if attempt < max_retries:
                    await asyncio.sleep(min(2 ** attempt, 10))  # Exponential backoff
                    
        return False

    async def send(self, data: str) -> None:
        """Send data through WebSocket.
        
        Args:
            data: JSON string to send
            
        Raises:
            StreamError: If not connected or send fails
        """
        if not self.websocket or not self.connected:
            raise StreamError("WebSocket not connected")
            
        try:
            await self.websocket.send(data)
        except Exception as e:
            self.connected = False
            raise StreamError(f"WebSocket send failed: {e}") from e

    async def recv(self) -> str:
        """Receive data from WebSocket.
        
        Returns:
            Received message as string
            
        Raises:
            StreamError: If not connected or receive fails
        """
        if not self.websocket or not self.connected:
            raise StreamError("WebSocket not connected")
            
        try:
            message = await self.websocket.recv()
            return str(message)
        except Exception as e:
            self.connected = False
            raise StreamError(f"WebSocket recv failed: {e}") from e

    async def close(self) -> None:
        """Close WebSocket connection cleanly.
        
        Uses close code 1000 (normal closure) and waits for closure confirmation.
        """
        # Stop heartbeat first
        self._stop_heartbeat = True
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self.websocket and self.connected:
            try:
                self.logger.event("ws.closing", session_id=self.session_id)
                
                # Close with normal closure code
                await self.websocket.close(code=1000)
                
                # Wait for closure to complete
                await self.websocket.wait_closed()
                
                self.logger.event("ws.closed", session_id=self.session_id)
                
            except Exception as e:
                self.logger.event("ws.close_error", error=str(e))
            finally:
                self.websocket = None
                self.connected = False
                self.session_id = ""

    async def _heartbeat_loop(self) -> None:
        """Heartbeat loop to keep connection alive."""
        while not self._stop_heartbeat and self.connected:
            try:
                await asyncio.sleep(self.ping_interval_s)
                
                if self._stop_heartbeat or not self.connected:
                    break
                    
                # WebSocket library handles ping automatically via ping_interval
                # We just need to check if connection is still alive
                if self.websocket and self.websocket.closed:
                    self.logger.event("ws.heartbeat.connection_closed")
                    self.connected = False
                    break
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.event("ws.heartbeat.error", error=str(e))
                self.connected = False
                break

    def _mask_endpoint(self, endpoint: str) -> str:
        """Mask sensitive parts of endpoint for logging.
        
        Args:
            endpoint: WebSocket endpoint URL
            
        Returns:
            Masked endpoint safe for logging
        """
        if not endpoint:
            return "not configured"
            
        # Mask model parameter if present
        return endpoint.replace("model=", "model=***")


class ReconnectingTransport:
    """WebSocket transport with automatic reconnection."""
    
    def __init__(self, endpoint: str, auth_header: str,
                 max_retries: int = 6, base_ms: int = 250, max_ms: int = 5000,
                 ping_interval_s: int = 10, logger: voice_logging.VoiceLogger | None = None):
        self.endpoint = endpoint
        self.auth_header = auth_header
        self.max_retries = max_retries
        self.base_ms = base_ms
        self.max_ms = max_ms
        self.ping_interval_s = ping_interval_s
        self.logger = logger or voice_logging.get_logger(__name__)
        
        self.transport: WebSocketTransport | None = None
        self.retry_count = 0

    async def ensure_connected(self) -> bool:
        """Ensure WebSocket connection is established.
        
        Returns:
            True if connected (or reconnected)
        """
        if self.transport and self.transport.connected:
            return True
            
        return await self._reconnect()

    async def _reconnect(self) -> bool:
        """Attempt to reconnect with exponential backoff."""
        while self.retry_count < self.max_retries:
            # Clean up old transport
            if self.transport:
                await self.transport.close()
                
            # Create new transport
            self.transport = WebSocketTransport(
                self.endpoint, 
                self.auth_header,
                self.ping_interval_s,
                self.logger
            )
            
            # Calculate backoff delay
            delay_ms = min(self.base_ms * (2 ** self.retry_count), self.max_ms)
            
            if self.retry_count > 0:
                self.logger.event("ws.reconnect.delay", 
                                delay_ms=delay_ms, retry=self.retry_count)
                await asyncio.sleep(delay_ms / 1000.0)
            
            # Attempt connection
            if await self.transport.connect():
                self.retry_count = 0
                return True
                
            self.retry_count += 1
            self.logger.event("ws.reconnect.failed", 
                            retry=self.retry_count, max_retries=self.max_retries)
            
        self.logger.event("ws.reconnect.exhausted", max_retries=self.max_retries)
        return False

    async def send(self, data: str) -> None:
        """Send data, reconnecting if needed."""
        if not await self.ensure_connected():
            raise StreamError("Cannot establish WebSocket connection")
            
        await self.transport.send(data)

    async def recv(self) -> str:
        """Receive data, reconnecting if needed.""" 
        if not await self.ensure_connected():
            raise StreamError("Cannot establish WebSocket connection")
            
        return await self.transport.recv()

    async def close(self) -> None:
        """Close transport connection."""
        if self.transport:
            await self.transport.close()
            self.transport = None
        self.retry_count = 0