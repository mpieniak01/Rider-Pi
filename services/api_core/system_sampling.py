"""Shared demand-driven system sampling; HTTP readers never advance CPU counters."""

from __future__ import annotations

import copy
import threading
import time
import uuid
from collections import deque
from pathlib import Path

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
        self.instance_id = uuid.uuid4().hex
        try:
            self.boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except OSError:
            self.boot_id = None
        self.generation = 0
        self.sequence = 0
        self.state = "idle"
        self.error_count = 0
        self.last_error_at = None
        self.last_error_code = None
        self.last_success_mono = None
        self.retry_at = 0.0

    def _sample_cpu(self):
        idle, total = self.cpu_reader()
        if total <= 0:
            self.previous = None
            self.idle_delta = self.total_delta = self.peak = 0.0
            return
        if total > 0:
            if self.previous is not None:
                di, dt = idle - self.previous[0], total - self.previous[1]
                if dt > 0 and di >= 0:
                    self.idle_delta += di
                    self.total_delta += dt
                    self.peak = max(self.peak, max(0.0, min(100.0, 100 * (1 - di / dt))))
            self.previous = (idle, total)

    def sample(self):
        with self.lock:
            now = self.clock()
            self._sample_cpu()
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
            self.sequence += 1
            self.history.append(
                (row["ts"], row["cpu_pct"], row["mem"]["pct"], row["cpu_peak_pct"], now, self.generation, self.sequence)
            )
            self.last_success_mono = now
            self.state = "collecting" if cpu is not None else "warming"
            # Keep the one-second phase even when a timer wakes slightly early/late.
            self.summary_at = (
                self.summary_at + SUMMARY_INTERVAL_S
                if self.summary_at is not None and now - self.summary_at < 2 * SUMMARY_INTERVAL_S
                else now
            )
            self.idle_delta = self.total_delta = self.peak = 0.0

    def _safe_sample(self):
        if self.clock() < self.retry_at:
            return
        try:
            self.sample()
        except Exception as error:
            # Keep the producer alive; retry on the summary beat, never a hot loop.
            self.state = "error"
            self.error_count += 1
            self.last_error_at = self.wall_clock()
            self.last_error_code = type(error).__name__
            self.summary_at = self.clock()
            self.retry_at = self.clock() + SUMMARY_INTERVAL_S
            self.previous = None
            self.idle_delta = self.total_delta = self.peak = 0.0

    def _run(self):
        deadline = self.clock()
        try:
            while True:
                deadline += CPU_INTERVAL_S
                time.sleep(max(0.0, deadline - self.clock()))
                with self.lock:
                    if self.clock() - self.last_access >= IDLE_TIMEOUT_S:
                        self.state = "idle"
                        return
                    self._safe_sample()
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
                self.generation += 1
                self._safe_sample()
                self.thread = threading.Thread(target=self._run, name="system-sampler", daemon=True)
                self.thread.start()
            row = (
                copy.deepcopy(self.latest)
                if self.latest is not None
                else {
                    "ts": None,
                    "cpu_pct": None,
                    "cpu_peak_pct": None,
                    "temp_c": None,
                    "load": dict.fromkeys(("1", "5", "15")),
                    "mem": dict.fromkeys(("pct", "total", "used", "available")),
                    "disk": dict.fromkeys(("pct", "total", "used", "free")),
                    "os": {},
                    "sampling": {},
                }
            )
            row["stale"] = self.state == "error"
            row["observation"] = {
                "boot_id": self.boot_id,
                "instance_id": self.instance_id,
                "generation": self.generation,
                "sequence": self.sequence,
                "state": self.state,
                "error_count": self.error_count,
                "last_error_at": self.last_error_at,
                "last_error_code": self.last_error_code,
                "age_s": max(0.0, self.clock() - self.last_success_mono)
                if self.last_success_mono is not None
                else None,
                "monotonic_s": self.last_success_mono,
            }
            history = list(self.history)
            row.update(
                hist_ts=[item[0] for item in history],
                hist_cpu=[item[1] for item in history],
                hist_mem=[item[2] for item in history],
                hist_cpu_peak=[item[3] for item in history],
                hist_mono=[item[4] for item in history],
                hist_generation=[item[5] for item in history],
                hist_seq=[item[6] for item in history],
            )
            return row
