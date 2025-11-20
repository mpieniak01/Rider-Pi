"""Common signal handler for graceful shutdown across Rider-Pi services.

This module provides a reusable signal handler that can be used by any service
to ensure proper cleanup on SIGTERM and SIGINT.
"""

from __future__ import annotations

import atexit
import signal
import sys
from typing import Callable


class GracefulShutdown:
    """Handles SIGTERM/SIGINT and triggers registered cleanup callbacks.

    Usage:
        shutdown = GracefulShutdown()
        shutdown.register(cleanup_function)
        shutdown.setup()
    """

    def __init__(self):
        self._callbacks: list[Callable[[], None]] = []
        self._shutdown_triggered = False

    def register(self, callback: Callable[[], None]) -> None:
        """Register a cleanup callback to be called on shutdown."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def _handle_signal(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        if self._shutdown_triggered:
            return
        self._shutdown_triggered = True

        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        print(f"[shutdown] Received {sig_name}, cleaning up...", file=sys.stderr)

        self._cleanup()
        sys.exit(0)

    def _cleanup(self) -> None:
        """Execute all registered cleanup callbacks."""
        for callback in self._callbacks:
            try:
                callback()
            except Exception as e:
                print(f"[shutdown] Error during cleanup: {e}", file=sys.stderr)

    def setup(self) -> None:
        """Install signal handlers for SIGTERM and SIGINT."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        # Also register atexit as a fallback
        atexit.register(self._cleanup)
