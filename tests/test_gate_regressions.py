"""Quality-gate regressions run on isolated files and fake effects only."""

from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.voice.web_audio import _maybe_gain
from drivers.lcd import lease

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    spec = importlib.util.spec_from_file_location("gate_fixture", ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "public", "foreign"])
def test_lcd_lock_rejects_unsafe_entries_before_acquiring_ownership(tmp_path, monkeypatch, kind):
    target = tmp_path / "private"
    target.write_bytes(b"preserve")
    path = tmp_path / "lcd.lock"
    monkeypatch.setenv("RIDER_LCD_OWNER_LOCK", str(path))
    if kind == "symlink":
        path.symlink_to(target)
    elif kind == "hardlink":
        os.link(target, path)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.write_bytes(b"old-lock")
        if kind == "public":
            path.chmod(0o666)
        else:
            original = os.fstat

            def foreign(fd):
                info = original(fd)
                if stat.S_ISREG(info.st_mode):
                    values = list(info)
                    values[4] = os.geteuid() + 100
                    return os.stat_result(values)
                return info

            monkeypatch.setattr(lease.os, "fstat", foreign)
    with pytest.raises(OSError):
        lease.LCDLease()
    assert target.read_bytes() == b"preserve"


def test_lcd_lock_keeps_stable_inode_and_releases_on_close(tmp_path, monkeypatch):
    path = tmp_path / "lcd.lock"
    monkeypatch.setenv("RIDER_LCD_OWNER_LOCK", str(path))
    first = lease.LCDLease()
    inode = path.stat().st_ino
    with pytest.raises(RuntimeError, match="lcd_owned"):
        lease.LCDLease()
    first.close()
    with lease.LCDLease():
        assert path.stat().st_ino == inode


def test_lcd_boot_root_owner_remains_compatible_with_service_reader(tmp_path, monkeypatch):
    path = tmp_path / "lcd.lock"
    path.touch(mode=0o644)
    monkeypatch.setenv("RIDER_LCD_OWNER_LOCK", str(path))
    original = os.fstat

    def root_owner(fd):
        values = list(original(fd))
        values[4] = 0
        return os.stat_result(values)

    monkeypatch.setattr(lease.os, "fstat", root_owner)
    with lease.LCDLease():
        assert path.stat().st_size == 0


def test_option_like_git_references_never_reach_git(tmp_path, monkeypatch):
    policy = load("scripts/dev_check-file-length.py")
    monkeypatch.setattr(policy.subprocess, "check_output", lambda *a, **k: pytest.fail("must reject before Git"))
    with pytest.raises(ValueError, match="invalid_git_reference"):
        policy.changed_files(tmp_path, "--output=victim", "HEAD")
    benchmark = load("scripts/face_benchmark.py")
    with pytest.raises(ValueError, match="invalid_baseline_reference"):
        benchmark.controller_class("--upload-pack=malicious")


def test_neutral_and_near_neutral_gain_avoid_reencoding_audio():
    context = SimpleNamespace(audioop=SimpleNamespace(mul=lambda *a: pytest.fail("neutral gain must preserve PCM")))
    assert _maybe_gain(context, b"pcm", 1.0) == b"pcm"
    assert _maybe_gain(context, b"pcm", 1.0 + 1e-12) == b"pcm"


def test_javascript_report_uses_actual_measured_lines_and_rejects_external_paths(tmp_path, monkeypatch):
    reports = load("tests/quality_reports.py")
    monkeypatch.setattr(reports, "ROOT", tmp_path)
    (tmp_path / "web").mkdir()
    (tmp_path / "web/source.js").write_text("first();\nsecond();\n")
    raw = tmp_path / "raw.lcov"
    output = tmp_path / "lcov.info"
    raw.write_text("SF:web\\source.js\nFN:undefined,vm_function\nDA:1,2\nDA:2,0\nDA:3,1\nend_of_record\n")
    reports.javascript_report(raw, output)
    assert "DA:1,2" in output.read_text()
    assert "DA:2,0" in output.read_text()
    assert "DA:3" not in output.read_text()
    raw.write_text("SF:../outside.js\nDA:1,1\nend_of_record\n")
    with pytest.raises(ValueError, match="outside_repository"):
        reports.javascript_report(raw, output)


@pytest.mark.parametrize(
    "value",
    [
        "http://remote.example:8800",
        "http://192.168.1.5:8800",
        "ftp://remote.example",
        "https://user:password@remote.example",
        "https://remote.example/\r\nforged",
    ],
)
def test_remote_provider_rejects_cleartext_or_ambiguous_urls(value):
    from services.provider_registry import _peer_url

    with pytest.raises(ValueError):
        _peer_url(value)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("localhost:18815", "http://localhost:18815"),
        ("127.0.0.1:18815", "http://127.0.0.1:18815"),
        ("[::1]:18815", "http://[::1]:18815"),
        ("remote.example:8800", "https://remote.example:8800"),
    ],
)
def test_provider_defaults_preserve_loopback_and_require_remote_tls(value, expected):
    from services.provider_registry import _peer_url

    assert _peer_url(value) == expected


@pytest.mark.parametrize("outside", ["../outside.txt", "sibling-link/output.txt"])
def test_cli_outputs_cannot_escape_invocation_directory(tmp_path, monkeypatch, outside):
    from services.core.cli_files import write_output

    working = tmp_path / "working"
    working.mkdir()
    (working / "sibling-link").symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.chdir(working)
    with pytest.raises(ValueError, match="outside_working_directory"):
        write_output(outside, b"unsafe")
    assert not (tmp_path / "outside.txt").exists()
    assert not (tmp_path / "output.txt").exists()


def test_cli_outputs_never_clobber_existing_content(tmp_path, monkeypatch):
    from services.core.cli_files import write_output

    monkeypatch.chdir(tmp_path)
    write_output("new/output.txt", b"complete")
    with pytest.raises(FileExistsError):
        write_output("new/output.txt", b"replacement")
    assert (tmp_path / "new/output.txt").read_bytes() == b"complete"
    assert stat.S_IMODE((tmp_path / "new/output.txt").stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "value",
    [
        "file:///etc/passwd",
        "http://attacker.example:8080",
        "http://127.0.0.1:22",
        "http://localhost:8080/private",
        "http://localhost:8080@attacker.example:8080",
    ],
)
def test_diagnostic_cli_rejects_unapproved_targets(value):
    diagnostic = load("scripts/diag_motion-status.py")
    with pytest.raises(ValueError):
        diagnostic.diagnostic_base(value)


def test_invalid_lcd_lease_is_unconfirmed_without_attempting_power_control(tmp_path, monkeypatch):
    from apps.ui.lcd_power import off_if_free

    path = tmp_path / "lcd.lock"
    path.symlink_to(tmp_path / "victim")
    monkeypatch.setenv("RIDER_LCD_OWNER_LOCK", str(path))
    result = off_if_free(
        probe=lambda: {"free": True, "holders": []},
        runner=lambda *a, **kw: pytest.fail("unsafe lease must not actuate"),
    )
    assert result["ok"] is False
    assert result["on"] is None
    assert result["error"] == "lcd_owned_or_unknown"


def test_ssh_payload_keeps_device_path_as_one_quoted_json_argument(tmp_path, monkeypatch):
    import json
    import shlex

    deploy = load("scripts/dev_pi-deploy.py")
    env_file = tmp_path / "ssh.env"
    env_file.touch(mode=0o600)
    monkeypatch.setattr(deploy, "run", lambda *a, **kw: SimpleNamespace(stdout="localhost\npi\n22\n"))
    captured = []

    def fake_ssh(args, **kwargs):
        captured.append(args)
        return SimpleNamespace(returncode=0, stdout=b'{"ok":true}', stderr=b"")

    monkeypatch.setattr(deploy.subprocess, "run", fake_ssh)
    path = str(tmp_path / "device's $(touch must-not-exist)")
    request = {"action": "status", "repo": path}
    assert deploy.ssh(env_file, request, b"") == {"ok": True}
    arguments = shlex.split(captured[0][-1])
    assert arguments[:2] == ["python3", "-c"]
    assert arguments[-2] == "_remote"
    assert json.loads(arguments[-1]) == request
    assert not (tmp_path / "must-not-exist").exists()


def test_diagnostic_rejects_unapproved_cli_target_before_building_a_network_opener(monkeypatch):
    import sys

    diagnostic = load("scripts/diag_motion-status.py")
    monkeypatch.setattr(sys, "argv", ["diag_motion-status.py", "http://attacker.example:8080"])
    monkeypatch.setattr(
        diagnostic.urllib.request, "build_opener", lambda *args: pytest.fail("Invalid target reached network setup")
    )
    with pytest.raises(ValueError, match="diagnostic_target_not_allowed"):
        diagnostic.main()


def test_real_urllib_redirect_dispatch_cannot_follow_an_unapproved_location():
    import io
    import urllib.request
    from email.message import Message
    from unittest.mock import Mock

    diagnostic = load("scripts/diag_motion-status.py")
    opener = urllib.request.build_opener(diagnostic.NoRedirect())
    opener.open = Mock(side_effect=AssertionError("Redirect reached a second request"))
    request = urllib.request.Request("http://127.0.0.1:8080/healthz")
    headers = Message()
    headers["Location"] = "http://attacker.example/private"
    response = io.BytesIO(b"")
    with pytest.raises(ValueError, match="diagnostic_redirect_not_allowed"):
        opener.error("http", request, response, 302, "Found", headers)
    opener.open.assert_not_called()


def test_git_reference_shell_syntax_is_only_data_and_never_executes(tmp_path):
    import subprocess

    guard = load("scripts/dev_check-file-length.py")
    root = Path(__file__).resolve().parents[1]
    sentinel = tmp_path / "unexpected"
    reference = "HEAD; touch " + str(sentinel)
    with pytest.raises(subprocess.CalledProcessError):
        guard.changed_files(root, "HEAD", reference)
    assert not sentinel.exists()
