"""Hardware-free sampling checks: no UART, API daemon or robot connection."""

from collections import deque

from services.api_core import system_info
from services.api_core.system_sampling import SystemSampler


def fixture():
    clock = [0.0]
    counters = [100.0, 200.0]
    calls = []

    def collect(slow):
        calls.append(slow)
        return {
            "mem": {"pct": 25.0, "total": 100, "used": 25, "available": 75},
            "disk": {"pct": 10.0, "total": 100, "used": 10, "free": 90},
            "load": {"1": 0, "5": 0, "15": 0},
            "temp_c": 40,
            "os": {},
        }

    sampler = SystemSampler(
        lambda: tuple(counters), collect, clock=lambda: clock[0], wall_clock=lambda: 1000 + clock[0]
    )
    return sampler, clock, counters, calls


def advance(sampler, clock, counters, busy):
    clock[0] += 0.25
    counters[0] += 25 * (1 - busy / 100)
    counters[1] += 25
    sampler.sample()


def test_weighted_one_second_average_retains_short_peak():
    sampler, clock, counters, _ = fixture()
    sampler.sample()
    for busy in (0, 100, 0, 0):
        advance(sampler, clock, counters, busy)
    assert sampler.latest["cpu_pct"] == 25
    assert sampler.latest["cpu_peak_pct"] == 100
    assert sampler.history[-1] == (1001, 25, 25, 100)


def test_http_readers_share_one_sample_and_do_not_advance_counters(monkeypatch):
    sampler, clock, counters, calls = fixture()
    sampler.sample()
    for _ in range(4):
        advance(sampler, clock, counters, 0)
    sampler.thread = object()  # Pure reader exercise; no background thread.
    monkeypatch.setattr(system_info, "_sampler", sampler)
    cpu, mem = deque(maxlen=60), deque(maxlen=60)
    for _ in range(20):
        row = system_info.get_sysinfo(cpu, mem)
        assert row["cpu_pct"] == row["hist_cpu"][-1]
        assert row["cpu_peak_pct"] == row["hist_cpu_peak"][-1]
        assert row["ts"] == row["hist_ts"][-1]
        row["hist_cpu"].append(99)  # Readers cannot corrupt the internal history.
    assert calls == [True, False]
    assert len(cpu) == len(mem) == 1
    advance(sampler, clock, counters, 60)
    assert system_info.cpu_percent() == 0  # No one-second sample yet.


def test_slow_reads_once_per_minute_and_history_is_bounded():
    sampler, clock, counters, calls = fixture()
    sampler.sample()
    for _ in range(280):
        advance(sampler, clock, counters, 20)
    assert sum(calls) == 2
    assert len(sampler.history) == 60
    assert sampler.history[-1][0] - sampler.history[0][0] == 59


def test_counter_reset_never_invents_a_peak():
    sampler, clock, counters, _ = fixture()
    sampler.sample()
    counters[:] = [0, 1]
    clock[0] = 1
    sampler.sample()
    assert sampler.latest["cpu_pct"] == sampler.latest["cpu_peak_pct"] is None


def test_idle_sampler_stops_and_does_not_backfill_history(monkeypatch):
    sampler, clock, counters, _ = fixture()
    sampler.sample()
    sampler.thread = object()
    sampler.last_access = 0
    clock[0] = 31
    monkeypatch.setattr("services.api_core.system_sampling.time.sleep", lambda seconds: None)
    sampler._run()
    assert sampler.thread is sampler.previous is sampler.summary_at is None
    assert len(sampler.history) == 0
    sampler.sample()
    assert sampler.latest["ts"] == 1031
    assert len(sampler.history) == 0
    assert sampler.latest["cpu_pct"] is None


def test_proc_cpu_excludes_iowait_and_duplicate_guest(monkeypatch):
    from io import StringIO

    monkeypatch.setattr("builtins.open", lambda path: StringIO("cpu 100 10 20 200 30 4 6 8 40 5\n"))
    assert system_info._cpu_pct_sample() == (230, 378)


def test_same_cpu_sample_is_used_by_legacy_endpoints(monkeypatch):
    from flask import Flask

    sampler, clock, counters, _ = fixture()
    sampler.sample()
    for _ in range(4):
        advance(sampler, clock, counters, 80)
    sampler.thread = object()
    monkeypatch.setattr(system_info, "_sampler", sampler)
    with Flask(__name__).app_context():
        payload = system_info.sysinfo().get_json()
        metrics = system_info.metrics().get_data(as_text=True)
    assert payload["cpu_pct"] == payload["hist_cpu"][-1] == 80
    assert payload["cpu_peak_pct"] == payload["hist_cpu_peak"][-1] == 80
    assert payload["sampling"]["panel_intervals_ms"]["services"] == 5000
    assert "rider_cpu_pct 80.0" in metrics


def test_summary_phase_does_not_drift_by_a_quarter_second():
    sampler, clock, counters, _ = fixture()
    sampler.sample()
    for instant in (0.25, 0.5, 0.75, 1.0001, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0):
        clock[0] = instant
        counters[0] += 10
        counters[1] += 25
        sampler.sample()
    assert [row[0] for row in sampler.history] == [1001.0001, 1002, 1003]


def test_first_snapshot_has_other_metrics_but_no_cpu_or_prometheus_sample(monkeypatch):
    from flask import Flask

    sampler, _, _, calls = fixture()
    sampler.sample()
    sampler.thread = object()
    monkeypatch.setattr(system_info, "_sampler", sampler)
    with Flask(__name__).app_context():
        row = system_info.sysinfo().get_json()
        metrics = system_info.metrics().get_data(as_text=True)
    assert row["cpu_pct"] is row["cpu_peak_pct"] is None
    assert row["mem_pct"] == 25
    assert row["disk_pct"] == 10
    assert row["temp_c"] == 40
    assert row["hist_cpu"] == row["hist_ts"] == []
    assert calls == [True]
    assert "rider_cpu_pct" not in metrics
    assert "rider_mem_pct 25" in metrics


def test_missing_cpu_delta_does_not_publish_zero_or_history():
    sampler, clock, _, _ = fixture()
    sampler.sample()
    clock[0] = 1
    sampler.sample()
    assert sampler.latest["cpu_pct"] is sampler.latest["cpu_peak_pct"] is None
    assert not sampler.history
