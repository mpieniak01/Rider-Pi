from types import SimpleNamespace

import pytest

from common import uart_ownership


@pytest.mark.parametrize("stdout,rc,owners", [("p12\np34\n", 0, [12, 34]), ("", 1, [])])
def test_privileged_exact_uart_read(monkeypatch, stdout, rc, owners):
    calls = []
    monkeypatch.setattr(uart_ownership.os.path, "exists", lambda _: True)
    monkeypatch.setattr(uart_ownership.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        uart_ownership.subprocess,
        "run",
        lambda argv, **k: calls.append(argv) or SimpleNamespace(stdout=stdout, stderr="", returncode=rc),
    )
    row = uart_ownership.read_uart_owners()
    assert row["known"]
    assert row["owners"] == owners
    assert calls == [["/usr/bin/sudo", "-n", "/usr/bin/lsof", "-Fp", "--", "/dev/ttyAMA0"]]


@pytest.mark.parametrize(
    "stdout,stderr,rc",
    [("", "sudo denied", 1), ("pbad", "", 0), ("?", "", 0), ("", "", 2), ("", "", 0), ("p12", "", 1)],
)
def test_permission_malformed_query_never_claims_free(monkeypatch, stdout, stderr, rc):
    monkeypatch.setattr(uart_ownership.os.path, "exists", lambda _: True)
    monkeypatch.setattr(
        uart_ownership.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=stdout, stderr=stderr, returncode=rc)
    )
    row = uart_ownership.read_uart_owners()
    assert not row["known"]
    assert row["error"]
    assert row["unreadable"] == ["/dev/ttyAMA0"]


def test_only_motion_uart_is_allowed_without_any_io():
    assert not uart_ownership.read_uart_owners("/dev/video0")["known"]
