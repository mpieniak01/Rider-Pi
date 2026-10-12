"""Shared demand-driven system sampling; HTTP readers never advance CPU counters."""

from __future__ import annotations

import copy
import threading
import time
from collections import deque

PANEL_INTERVALS_MS = {
    "telemetry": 1000,
    "system": 2000,
    "services": 5000,
    "inventory": 10000,
    "vision": 2000,
    "metrics": 10000,
}
CPU_INTERVAL_S = 0.25
SUMMARY_INTERVAL_S = 1.0
DISK_INTERVAL_S = 60.0
IDLE_TIMEOUT_S = 30.0


class SystemSampler:
    """One sampler per API process; sleeping when nobody requests metrics."""

    def __init__(self, cpu_reader, collect, *, clock=time.monotonic, wall_clock=time.time):
        self.cpu_reader = cpu_reader
        self.collect = collect
        self.clock = clock
        self.wall_clock = wall_clock
        self.lock = threading.RLock()
        self.thread = None
        self.last_access = None
        self.previous = None
        self.summary_at = None
        self.disk_at = None
        self.idle_delta = self.total_delta = 0.0
        self.peak = 0.0
        self.latest = None
        self.history = deque(maxlen=60)

    def sample(self):
        with self.lock:
            now = self.clock()
            idle, total = self.cpu_reader()
            if total > 0:
                if self.previous is not None:
                    di, dt = idle - self.previous[0], total - self.previous[1]
                    if dt > 0 and di >= 0:
                        self.idle_delta += di
                        self.total_delta += dt
                        self.peak = max(self.peak, max(0.0, min(100.0, 100 * (1 - di / dt))))
                self.previous = (idle, total)
            if self.summary_at is not None and now - self.summary_at < SUMMARY_INTERVAL_S - 0.001:
                return
            slow = self.disk_at is None or now - self.disk_at >= DISK_INTERVAL_S
            row = self.collect(slow)
            if slow:
                self.disk_at = now
            cpu = 100 * (1 - self.idle_delta / self.total_delta) if self.total_delta > 0 else None
            row.update(
                ts=self.wall_clock(),
                cpu_pct=round(max(0.0, min(100.0, cpu)), 1) if cpu is not None else None,
                cpu_peak_pct=round(self.peak, 1) if cpu is not None else None,
                sampling={
                    "cpu_interval_ms": 250,
                    "summary_interval_ms": 1000,
                    "disk_interval_ms": 60000,
                    "panel_intervals_ms": dict(PANEL_INTERVALS_MS),
                },
            )
            self.latest = row
            if cpu is not None:
                self.history.append((row["ts"], row["cpu_pct"], row["mem"]["pct"], row["cpu_peak_pct"]))
            # Keep the one-second phase even when a timer wakes slightly early/late.
            self.summary_at = (
                self.summary_at + SUMMARY_INTERVAL_S
                if self.summary_at is not None and now - self.summary_at < 2 * SUMMARY_INTERVAL_S
                else now
            )
            self.idle_delta = self.total_delta = self.peak = 0.0

    def _run(self):
        deadline = self.clock()
        try:
            while True:
                deadline += CPU_INTERVAL_S
                time.sleep(max(0.0, deadline - self.clock()))
                with self.lock:
                    if self.clock() - self.last_access >= IDLE_TIMEOUT_S:
                        return
                self.sample()
                if self.clock() > deadline + CPU_INTERVAL_S:
                    # Skip missed ticks, do not replay a burst after a slow read.
                    deadline = self.clock()
        finally:
            with self.lock:
                self.thread = None
                self.previous = None
                self.summary_at = None
                self.idle_delta = self.total_delta = self.peak = 0.0

    def snapshot(self):
        with self.lock:
            self.last_access = self.clock()
            if self.thread is None:
                # Do not invent samples across an idle interval.
                self.sample()
                self.thread = threading.Thread(target=self._run, name="system-sampler", daemon=True)
                self.thread.start()
            row = copy.deepcopy(self.latest)
            history = list(self.history)
            row.update(
                hist_ts=[item[0] for item in history],
                hist_cpu=[item[1] for item in history],
                hist_mem=[item[2] for item in history],
                hist_cpu_peak=[item[3] for item in history],
            )
            return row
