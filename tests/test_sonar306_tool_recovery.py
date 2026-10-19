"""Software-only recovery and foreground cleanup for public tool clients."""

import json
import runpy
import signal
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import resource_ctl
from services.api_core import face_anim

ROOT = Path(__file__).resolve().parents[1]


def test_unchanged_preview_retains_both_restart_flags_before_backend_calls(tmp_path, monkeypatch):
    function = runpy.run_path(str(ROOT / "scripts/dev_pi-deploy.py"))["_unchanged_preview"]
    namespace = function.__globals__
    previous = {"restart_api": False, "restart_motion": False}
    path = tmp_path / "record.json"
    calls = []

    def operation(args):
        assert json.loads(path.read_text())["restart_motion"] is True
        calls.append(args)

    def api():
        assert json.loads(path.read_text())["restart_api"] is True
        calls.append("api")

    monkeypatch.setitem(namespace, "run", operation)
    monkeypatch.setitem(namespace, "restart_api", api)
    monkeypatch.setitem(namespace, "status", lambda *_args: {"commit": "unchanged"})
    result = function(tmp_path, path, {"restart_motion": True}, previous, True)
    assert result["unchanged"] is True
    assert calls == [
        ["sudo", "-n", "systemctl", "restart", "motion-executor.service"],
        ["systemctl", "is-active", "motion-executor.service"],
        "api",
    ]
    assert previous == {"restart_api": False, "restart_motion": False}


@pytest.mark.parametrize("has_previous", [False, True])
def test_failed_preview_restores_record_before_services_and_preserves_original_failure(
    tmp_path, monkeypatch, has_previous
):
    function = runpy.run_path(str(ROOT / "scripts/dev_pi-deploy.py"))["_switch_preview_checkout"]
    namespace = function.__globals__
    previous = {"commit": "old"} if has_previous else None
    path = tmp_path / "record.json"
    events = []
    failure = RuntimeError("checkout failed")

    def git(_repo, *args):
        if args[0] == "switch":
            raise failure
        return "old"

    def operation(args):
        if "start" in args:
            if has_previous:
                assert json.loads(path.read_text()) == previous
            else:
                assert not path.exists()
        events.append(args)

    monkeypatch.setitem(namespace, "git", git)
    monkeypatch.setitem(namespace, "run", operation)
    monkeypatch.setitem(namespace, "pause_resources", lambda: events.append("pause"))
    monkeypatch.setitem(namespace, "restart_api", lambda: events.append("api"))
    monkeypatch.setitem(namespace, "resume_display", lambda active: events.append(("display", active)))
    failed_result = SimpleNamespace(returncode=1)
    with pytest.raises(RuntimeError) as caught:
        function(
            tmp_path,
            path,
            {"restart_motion": True},
            previous,
            "old",
            "new",
            "preview",
            failed_result,
            {"commit": "new"},
            True,
            False,
        )
    assert caught.value is failure
    assert events[-3:] == [["sudo", "-n", "systemctl", "start", "motion-executor.service"], "api", ("display", False)]


@pytest.mark.parametrize("interrupted", [False, True])
def test_direct_face_restores_signal_handler_before_owned_cleanup(monkeypatch, interrupted):
    events = []
    previous = object()
    stop_result = {"ok": True, "state": {"playing": False}}
    client = SimpleNamespace(request=lambda *args: events.append(("request", args)) or stop_result)
    finished = SimpleNamespace(set=Mock())

    def wait(_seconds):
        if interrupted:
            raise KeyboardInterrupt()
        return False

    finished.wait = wait
    monkeypatch.setattr(threading, "Event", lambda: finished)
    monkeypatch.setattr(signal, "getsignal", lambda *_args: previous)
    monkeypatch.setattr(signal, "signal", lambda _number, handler: events.append(("signal", handler)))
    monkeypatch.setattr(
        face_anim, "get_state", Mock(side_effect=[{"state": {"playing": True}}, {"state": {"playing": False}}])
    )
    if interrupted:
        with pytest.raises(KeyboardInterrupt):
            resource_ctl._wait_direct_face(client, {"ok": True})
    else:
        assert resource_ctl._wait_direct_face(client, {"ok": True}) is stop_result
    assert events[-2:] == [("signal", previous), ("request", ("/api/face-studio/runtime/stop", "POST", {}))]


@pytest.mark.parametrize(
    "duration,valid", [(None, True), (1, True), (300, True), (0, False), (301, False), (True, False), ("5", False)]
)
def test_direct_face_payload_admission_precedes_request(monkeypatch, duration, valid):
    calls = []
    client = SimpleNamespace(request=lambda *args: calls.append(args) or {"ok": True})
    monkeypatch.setattr(resource_ctl, "_client", lambda _args: client)
    monkeypatch.setattr(resource_ctl, "_wait_direct_face", lambda _client, result: result)
    payload = {} if duration is None else {"duration_s": duration}
    args = SimpleNamespace(payload=json.dumps(payload), direct=True, kind="face", action="play", name=None)
    if valid:
        assert resource_ctl._request_resource(args) == {"ok": True}
        assert calls == [
            (
                "/api/face-studio/runtime/play",
                "POST",
                {"action": "play", "duration_s": 5 if duration is None else duration},
            )
        ]
    else:
        with pytest.raises(ValueError, match="direct_face_requires_bounded_duration"):
            resource_ctl._request_resource(args)
        assert calls == []


def test_direct_client_selection_is_local_only_and_receives_original_url(monkeypatch):
    sentinel = object()
    constructor = Mock(return_value=sentinel)
    monkeypatch.setitem(sys.modules, "common.local_api_client", SimpleNamespace(LocalAPIClient=constructor))
    assert resource_ctl._client(SimpleNamespace(direct=True, url="http://device.invalid:8080")) is sentinel
    constructor.assert_called_once_with("http://device.invalid:8080")
