# apps/voice/ws_transport.py
"""
WebSocket transport utilities for streaming voice service.

Extracted from svc_stream.py and transport.py (Issue mpieniak01/Rider-Pi#80 - PR-1 refactoring).
Provides WebSocket I/O utilities:
- Queue management with backpressure control
- Retry and exponential backoff helpers
- Connection state tracking
- Ping/pong heartbeat utilities

NO API CHANGES - pure extraction of transport utilities.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any


# ────────────────────────────────────────────────────────────────────────────
# Configuration and state
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class WebSocketConfig:
    """WebSocket connection configuration."""

    endpoint: str
    ping_interval_s: float = 20.0
    ping_timeout_s: float = 10.0
    max_size: int | None = None  # None = unlimited (for large audio frames)
    compression: str | None = None  # None = no compression (lower latency)


@dataclass
class RetryConfig:
    """Retry and backoff configuration."""

    max_retries: int = 6
    base_delay_ms: int = 250
    max_delay_ms: int = 5000
    backoff_multiplier: float = 2.0


@dataclass
class QueueConfig:
    """Queue limits and backpressure configuration."""

    tx_queue_size: int = 100  # Max audio chunks in send queue
    rx_queue_size: int = 50  # Max messages in receive queue
    drop_on_full: bool = True  # Drop oldest on full vs. block


# ────────────────────────────────────────────────────────────────────────────
# Connection metrics
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class ConnectionMetrics:
    """WebSocket connection metrics."""

    connect_count: int = 0
    reconnect_count: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    messages_sent: int = 0
    messages_received: int = 0
    drops_tx: int = 0
    drops_rx: int = 0
    connection_start_ts: float = 0.0

    def reset_session(self) -> None:
        """Reset per-session metrics."""
        self.bytes_sent = 0
        self.bytes_received = 0
        self.messages_sent = 0
        self.messages_received = 0
        self.drops_tx = 0
        self.drops_rx = 0
        self.connection_start_ts = time.time()

    def record_connect(self, is_reconnect: bool = False) -> None:
        """Record connection event."""
        if is_reconnect:
            self.reconnect_count += 1
        else:
            self.connect_count += 1
        self.reset_session()

    def record_send(self, size: int) -> None:
        """Record message sent."""
        self.messages_sent += 1
        self.bytes_sent += size

    def record_recv(self, size: int) -> None:
        """Record message received."""
        self.messages_received += 1
        self.bytes_received += size

    def record_drop_tx(self) -> None:
        """Record TX queue drop."""
        self.drops_tx += 1

    def record_drop_rx(self) -> None:
        """Record RX queue drop."""
        self.drops_rx += 1

    def get_lifetime_s(self) -> float:
        """Get connection lifetime in seconds."""
        if self.connection_start_ts > 0:
            return time.time() - self.connection_start_ts
        return 0.0


# ────────────────────────────────────────────────────────────────────────────
# Retry and backoff helpers
# ────────────────────────────────────────────────────────────────────────────
def calculate_backoff_delay(retry_count: int, config: RetryConfig) -> float:
    """Calculate exponential backoff delay in seconds.

    Args:
        retry_count: Current retry attempt (0-indexed)
        config: Retry configuration

    Returns:
        Delay in seconds
    """
    delay_ms = min(
        config.base_delay_ms * (config.backoff_multiplier**retry_count),
        config.max_delay_ms,
    )
    return delay_ms / 1000.0


def should_retry(retry_count: int, config: RetryConfig) -> bool:
    """Check if should retry based on retry count.

    Args:
        retry_count: Current retry attempt (0-indexed)
        config: Retry configuration

    Returns:
        True if should retry
    """
    return retry_count < config.max_retries


# ────────────────────────────────────────────────────────────────────────────
# Queue management
# ────────────────────────────────────────────────────────────────────────────
class BoundedQueue:
    """Bounded async queue with drop-on-full policy.

    When queue is full, drops oldest item to make room for new item.
    Tracks drops for backpressure monitoring.
    """

    def __init__(self, maxsize: int, drop_on_full: bool = True):
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        self._drop_on_full = drop_on_full
        self._drop_count = 0
        self._maxsize = maxsize

    async def put(self, item: Any) -> bool:
        """Put item in queue.

        Args:
            item: Item to put in queue

        Returns:
            True if item was added, False if dropped
        """
        if self._queue.full():
            if self._drop_on_full:
                # Drop oldest item to make room
                try:
                    self._queue.get_nowait()
                    self._drop_count += 1
                except asyncio.QueueEmpty:
                    pass
            else:
                # Block until space available
                await self._queue.put(item)
                return True

        try:
            self._queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            self._drop_count += 1
            return False

    async def get(self) -> Any:
        """Get item from queue.

        Returns:
            Next item from queue
        """
        return await self._queue.get()

    def get_nowait(self) -> Any:
        """Get item from queue without blocking.

        Returns:
            Next item from queue

        Raises:
            asyncio.QueueEmpty: If queue is empty
        """
        return self._queue.get_nowait()

    def empty(self) -> bool:
        """Check if queue is empty."""
        return self._queue.empty()

    def full(self) -> bool:
        """Check if queue is full."""
        return self._queue.full()

    def qsize(self) -> int:
        """Get current queue size."""
        return self._queue.qsize()

    def maxsize(self) -> int:
        """Get maximum queue size."""
        return self._maxsize

    def drop_count(self) -> int:
        """Get number of dropped items."""
        return self._drop_count

    def reset_drops(self) -> None:
        """Reset drop counter."""
        self._drop_count = 0


# ────────────────────────────────────────────────────────────────────────────
# Environment variable helpers
# ────────────────────────────────────────────────────────────────────────────
def env_int(name: str, default: int) -> int:
    """Get integer from environment variable.

    Args:
        name: Environment variable name
        default: Default value if not set or invalid

    Returns:
        Integer value
    """
    try:
        raw = os.environ.get(name, "")
        return int(raw.strip() or default)
    except Exception:
        return default


def env_flag(name: str, default: bool = False) -> bool:
    """Get boolean flag from environment variable.

    Args:
        name: Environment variable name
        default: Default value if not set

    Returns:
        Boolean value
    """
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip() in ("1", "true", "True", "yes", "YES")


def env_float(name: str, default: float) -> float:
    """Get float from environment variable.

    Args:
        name: Environment variable name
        default: Default value if not set or invalid

    Returns:
        Float value
    """
    try:
        raw = os.environ.get(name, "")
        return float(raw.strip() or default)
    except Exception:
        return default
