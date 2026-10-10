from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

from services.api_core import features_api, resource_diag


@pytest.fixture(autouse=True)
def isolated_task_ownership(monkeypatch, tmp_path):
    monkeypatch.setattr(
        features_api,
        "feature_manager",
        SimpleNamespace(
            transaction=nullcontext,
            resource_consumers=lambda: {},
            _state_path=tmp_path / "feature_state.json",
        ),
    )


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


def test_release_audio_terminates_only_confirmed_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: dict[str, Any] = {}

    def fake_call(cmd: list[str]) -> dict[str, Any]:
        executed["cmd"] = cmd
        return {"ok": True}

    monkeypatch.setattr(resource_diag, "_call_release", fake_call)
    monkeypatch.setattr(
        resource_diag,
        "inspect",
        lambda _: {"state": "busy", "holders": [{"pid": pid, "service": "rider-voice.service"} for pid in [42, 43]]},
    )

    res = resource_diag.release("mic", limit_pids=[42, 43], force=True, operator_consent=True)
    assert res["ok"] is False
    assert res['signal_sent'] is True and res['pending'] is True and res['released'] is False
    cmd = executed["cmd"]
    assert cmd == ["sudo", "-n", "kill", "-TERM", "--", "42", "43"]


def test_release_camera_never_touches_lcd_or_spi(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: dict[str, Any] = {}

    def fake_call(cmd: list[str]) -> dict[str, Any]:
        executed["cmd"] = cmd
        return {"ok": True}

    monkeypatch.setattr(resource_diag, "_call_release", fake_call)
    monkeypatch.setattr(
        resource_diag,
        "inspect",
        lambda _: {"state": "busy", "holders": [{"pid": 77, "service": "camera-capture@raw.service"}]},
    )

    res = resource_diag.release("camera", limit_pids=[77], force=True, operator_consent=True)
    assert res["ok"] is False
    assert res['signal_sent'] is True and res['pending'] is True and res['released'] is False
    cmd = executed["cmd"]
    assert cmd == ["sudo", "-n", "kill", "-TERM", "--", "77"]


def test_lsof_partial_multi_path_result_reports_observed_busy_owner(monkeypatch):
    monkeypatch.setattr(resource_diag, "_existing_paths", lambda _: ["/dev/video0", "/dev/video1"])
    monkeypatch.setattr(resource_diag, "_systemd_unit_for_pid", lambda _: "camera-capture@raw.service")
    monkeypatch.setattr(
        resource_diag.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="p123\0cpython\0Lpi\0n/dev/video0\0\n", stderr="", returncode=1),
    )
    result = resource_diag.inspect("camera")
    assert result["state"] == "busy" and result["free"] is False
    assert result["holders"][0]["pid"] == 123


@pytest.mark.parametrize(
    "output",
    ["p123\0cpython\0", "garbled", "pbad\0n/dev/video0\0", "p0\0n/dev/video0\0", "p123\0n\0", "p123\0n  \0"],
)
def test_lsof_partial_incomplete_output_stays_unknown(monkeypatch, output):
    monkeypatch.setattr(resource_diag, "_existing_paths", lambda _: ["/dev/video0", "/dev/video1"])
    monkeypatch.setattr(
        resource_diag.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=output, stderr="", returncode=1)
    )
    result = resource_diag.inspect("camera")
    assert result["state"] == "unknown" and result["free"] is None and result["error"]


def test_lsof_single_uart_rc1_with_output_remains_unknown(monkeypatch):
    monkeypatch.setattr(resource_diag, "_existing_paths", lambda _: ["/dev/ttyAMA0"])
    monkeypatch.setattr(
        resource_diag.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="p123\0n/dev/ttyAMA0\0", stderr="", returncode=1),
    )
    result = resource_diag.inspect("uart")
    assert result["state"] == "unknown" and result["free"] is None
