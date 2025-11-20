"""
Graceful Shutdown Handler for Rider-Pi Services.

Provides a unified mechanism for handling SIGTERM and SIGINT signals,
allowing services to clean up resources (GPIO, SPI, subprocesses) before exit.
"""

from __future__ import annotations

import atexit
import signal
import sys
from collections.abc import Callable


class GracefulShutdown:
    """
    Context manager and signal handler for graceful shutdown.

    Usage:
        shutdown = GracefulShutdown()
        shutdown.register_cleanup(lambda: cleanup_resources())

        with shutdown:
            # main application loop
            while not shutdown.should_stop:
                do_work()
    """

    def __init__(self) -> None:
        self.should_stop = False
        self._cleanup_handlers: list[Callable[[], None]] = []
        self._signals_registered = False
        self._cleanup_done = False

    def register_cleanup(self, handler: Callable[[], None]) -> None:
        """Register a cleanup handler to be called on shutdown."""
        if handler not in self._cleanup_handlers:
            self._cleanup_handlers.append(handler)

    def _signal_handler(self, signum: int, frame) -> None:
        """Handle SIGTERM/SIGINT by triggering graceful shutdown."""
        signame = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        print(f"[shutdown] Received {signame}, initiating graceful shutdown...", file=sys.stderr, flush=True)
        self.should_stop = True
        self._run_cleanup()
        sys.exit(0)

    def _run_cleanup(self) -> None:
        """Execute all registered cleanup handlers."""
        if self._cleanup_done:
            return
        self._cleanup_done = True
        for handler in self._cleanup_handlers:
            try:
                handler()
            except Exception as e:
                print(f"[shutdown] Cleanup handler failed: {e}", file=sys.stderr, flush=True)

    def _register_signals(self) -> None:
        """Register signal handlers for SIGTERM and SIGINT."""
        if not self._signals_registered:
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
            atexit.register(self._run_cleanup)
            self._signals_registered = True

    def __enter__(self) -> GracefulShutdown:
        """Context manager entry - register signal handlers."""
        self._register_signals()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - run cleanup handlers."""
        self._run_cleanup()
