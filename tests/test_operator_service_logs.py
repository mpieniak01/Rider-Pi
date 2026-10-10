"""Journal fixtures are injected; no actual subprocess or service is inspected."""

import os

from services.api_core import service_logs
from services.api_core.service_logs import read_logs


def test_unknown_unit_never_calls_journal():
    def forbidden(command):
        raise AssertionError("Unexpected command")

    row = read_logs("unknown.service", catalog={"fixture.service": {}}, runner=forbidden)
    assert row["ok"] is False
    assert row["observed_at"] is None


def test_exact_readonly_command_and_bounded_lines():
    calls = []

    def fixture(command):
        calls.append(command)
        return {"returncode": 0, "stdout": "fixture line\n" * 100, "stderr": ""}

    row = read_logs("fixture.service", catalog={"fixture.service": {}}, runner=fixture)
    assert calls == [
        ["/usr/bin/journalctl", "--no-pager", "--quiet", "--output=short-iso", "-n", "50", "-u", "fixture.service"]
    ]
    assert row["ok"] is True
    assert len(row["lines"]) == 50
    assert row["source"] == "pi/systemd/journal"


def test_denial_timeout_and_process_error_remain_unknown():
    for result in (
        {"returncode": 1, "stderr": "Permission denied"},
        {"returncode": 0, "timeout": True},
        {"returncode": 1},
    ):
        row = read_logs("fixture.service", catalog={"fixture.service": {}}, runner=lambda command, value=result: value)
        assert row["ok"] is False
        assert row["observed_at"] is None
        assert row["lines"] == []


class FixtureProcess:
    def __init__(self, output=b"fixture output\n"):
        self.returncode = None
        self.killed = False
        self.stdout = self._pipe(output)
        self.stderr = self._pipe(b"")

    @staticmethod
    def _pipe(content):
        reader, writer = os.pipe()
        os.write(writer, content)
        os.close(writer)
        return os.fdopen(reader, "rb")

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def test_streaming_helper_reads_only_fixture_pipes_and_kills_at_byte_limit(monkeypatch):
    process = FixtureProcess()
    calls = []

    def fixture(command, **kwargs):
        calls.append((command, kwargs))
        return process

    monkeypatch.setattr(service_logs.subprocess, "Popen", fixture)
    monkeypatch.setattr(service_logs, "MAX_BYTES", 8)
    row = service_logs._journal(["fixture-only"])
    assert process.killed is True
    assert row["truncated"] is True
    assert len(row["stdout"].encode()) + len(row["stderr"].encode()) <= 8
    assert calls[0][0] == ["fixture-only"]
    assert calls[0][1]["shell"] is False


def test_streaming_helper_timeout_kills_only_the_fixture_process(monkeypatch):
    process = FixtureProcess()
    monkeypatch.setattr(service_logs.subprocess, "Popen", lambda *args, **kwargs: process)
    ticks = iter((0, 3, 3))
    monkeypatch.setattr(service_logs.time, "monotonic", lambda: next(ticks, 3))
    row = service_logs._journal(["fixture-only"])
    assert row["timeout"] is True
    assert process.killed is True
