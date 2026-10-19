"""Google feed worker lifecycle with stubbed polling, signals and clock."""

from __future__ import annotations

import json
import signal
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest


@pytest.fixture
def worker(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from apps.google_bridge import puller

    monkeypatch.setattr(puller, "STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(puller, "LAST_FILE", tmp_path / "last.json")
    monkeypatch.setattr(puller, "GOOGLE_ENABLED", True)
    monkeypatch.setattr(puller, "GOOGLE_POLL_S", 2)
    monkeypatch.setattr(puller, "_shutdown", False)
    monkeypatch.setattr(
        puller,
        "time",
        SimpleNamespace(time=Mock(return_value=1000.0), sleep=Mock(side_effect=AssertionError("Unexpected sleep"))),
    )
    monkeypatch.setattr(puller, "signal", SimpleNamespace(signal=Mock(), SIGINT=signal.SIGINT, SIGTERM=signal.SIGTERM))
    monkeypatch.setattr(puller, "poll_google", Mock(return_value=(True, {"feed": "sample"}, None)))
    monkeypatch.setattr(puller, "write_status", Mock(wraps=puller.write_status))
    monkeypatch.setattr(puller, "write_snapshot", Mock(wraps=puller.write_snapshot))
    return puller


def test_disabled_worker_waits_for_shutdown_without_polling(worker, monkeypatch):
    monkeypatch.setattr(worker, "GOOGLE_ENABLED", False)
    worker.time.sleep.side_effect = lambda seconds: worker.signal_handler(signal.SIGTERM, None)

    assert worker.main() is None

    worker.write_status.assert_called_once_with("off", 1000.0)
    worker.poll_google.assert_not_called()
    worker.write_snapshot.assert_not_called()
    worker.time.sleep.assert_called_once_with(1)
    assert worker._shutdown is True


def test_polling_worker_handles_shutdown_and_keeps_success_snapshot(worker):
    worker.time.sleep.side_effect = lambda seconds: worker.signal_handler(signal.SIGINT, None)

    assert worker.main() is None

    assert worker.signal.signal.call_args_list == [
        call(signal.SIGINT, worker.signal_handler),
        call(signal.SIGTERM, worker.signal_handler),
    ]
    assert worker.write_status.call_args_list == [call("enabled", 1000.0), call("ok", 1000.0, 0, 1)]
    worker.write_snapshot.assert_called_once_with(data={"feed": "sample"})
    worker.poll_google.assert_called_once_with()
    worker.time.sleep.assert_called_once_with(1)
    assert json.loads(worker.STATUS_FILE.read_text())["state"] == "ok"
    assert json.loads(worker.LAST_FILE.read_text())["data"] == {"feed": "sample"}


def test_failed_poll_is_reported_and_retried_after_poll_interval(worker):
    worker.poll_google.side_effect = [(False, None, "temporarily unavailable"), (True, {"feed": "recovered"}, None)]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            worker.signal_handler(signal.SIGTERM, None)

    worker.time.sleep.side_effect = sleep

    assert worker.main() is None

    assert sleeps == [1, 1, 1]
    assert worker.poll_google.call_count == 2
    assert worker.write_status.call_args_list == [
        call("enabled", 1000.0),
        call("error", 1000.0, 1, 1),
        call("ok", 1000.0, 1, 2),
    ]
    assert worker.write_snapshot.call_args_list == [
        call(error="temporarily unavailable"),
        call(data={"feed": "recovered"}),
    ]
    assert json.loads(worker.STATUS_FILE.read_text())["metrics"] == {"errors_24h": 1, "requests_24h": 2}


def test_unexpected_loop_error_preserves_five_second_retry(worker, caplog):
    worker.poll_google.side_effect = [RuntimeError("unexpected poll error"), (True, {"feed": "recovered"}, None)]

    def sleep(seconds):
        if seconds == 1:
            worker.signal_handler(signal.SIGTERM, None)

    worker.time.sleep.side_effect = sleep

    assert worker.main() is None

    assert worker.time.sleep.call_args_list == [call(5), call(1)]
    assert worker.poll_google.call_count == 2
    assert worker.write_status.call_args_list == [
        call("enabled", 1000.0),
        call("error", 1000.0, 1, 1),
        call("ok", 1000.0, 1, 2),
    ]
    assert worker.write_snapshot.call_args_list == [
        call(error="unexpected poll error"),
        call(data={"feed": "recovered"}),
    ]
    record = next(record for record in caplog.records if "Unexpected error in main loop" in record.message)
    assert record.exc_info[1].args == ("unexpected poll error",)


def test_startup_failure_propagates_instead_of_returning_success(worker):
    worker.signal.signal.side_effect = RuntimeError("cannot register signal handler")

    with pytest.raises(RuntimeError, match="cannot register signal handler"):
        worker.main()

    worker.poll_google.assert_not_called()
    worker.write_status.assert_not_called()
    worker.time.sleep.assert_not_called()


def test_poll_exception_keeps_failure_result_and_traceback(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from apps.google_bridge import puller

    failure = RuntimeError("Google source unavailable")
    source = Mock(side_effect=failure)
    monkeypatch.setattr(puller, "pseudocall_google", source)

    assert puller.poll_google() == (False, None, "Google source unavailable")

    source.assert_called_once_with()
    record = next(record for record in caplog.records if "Google poll failed" in record.message)
    assert record.exc_info[1] is failure
