from __future__ import annotations

from typing import Any

import pytest

from services.api_core import resource_diag


def test_inspect_mic_reports_holders(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_proc = resource_diag.ProcessInfo(
        pid=123,
        command="python3",
        user="pi",
        paths=["/dev/snd/pcmC0D0c", "/dev/snd/controlC0"],
    )

    monkeypatch.setattr(resource_diag, "_existing_paths", lambda _: ["/dev/snd/pcmC0D0c"])
    monkeypatch.setattr(resource_diag, "_run_lsof", lambda paths: [fake_proc])
    monkeypatch.setattr(
        resource_diag, "_systemd_unit_for_pid", lambda pid: "rider-voice.service" if pid == 123 else None
    )

    data = resource_diag.inspect("mic")
    assert data["resource"] == "mic"
    assert data["free"] is False
    assert data["holders"]
    holder = data["holders"][0]
    assert holder["pid"] == 123
    assert holder["service"] == "rider-voice.service"


def test_release_audio_uses_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: dict[str, Any] = {}

    def fake_call(cmd: list[str]) -> dict[str, Any]:
        executed["cmd"] = cmd
        return {"ok": True}

    monkeypatch.setattr(resource_diag, "_call_release", fake_call)

    res = resource_diag.release("mic", limit_pids=[42, 43])
    assert res["ok"] is True
    cmd = executed["cmd"]
    assert cmd[0].endswith("preflight.sh")
    assert "--capture" in cmd
    assert cmd.count("--limit-pid") == 2
    assert "42" in cmd and "43" in cmd


def test_release_camera_calls_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: dict[str, Any] = {}

    def fake_call(cmd: list[str]) -> dict[str, Any]:
        executed["cmd"] = cmd
        return {"ok": True}

    monkeypatch.setattr(resource_diag, "_call_release", fake_call)

    res = resource_diag.release("camera", limit_pids=[77])
    assert res["ok"] is True
    cmd = executed["cmd"]
    assert cmd[0].endswith("sys_camera-free.sh")
    assert "--pid" in cmd and "77" in cmd
