"""Deployment admission and failure journals with local files and inert backends."""

import json
import re
import runpy
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import resource_ctl, robot_ctl, systemd_reconcile

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def deploy():
    return runpy.run_path(str(ROOT / "scripts/dev_pi-deploy.py"))


@pytest.mark.parametrize(
    "path", ["config/local/secrets.env", ".env", "docs_pl/_done/private.txt", "models/private.bin"]
)
def test_explicit_scopes_never_admit_private_data(deploy, path):
    with pytest.raises(RuntimeError, match="protected path"):
        deploy["check_paths"]([path], restart_motion=True, resource_scope=True, vision_loop_scope=True)


def test_unchanged_preview_journals_restart_intent_before_backend_failure(deploy, monkeypatch, tmp_path):
    """Verify unchanged preview journals restart intent before backend failure."""
    function = deploy["_unchanged_preview"]
    namespace = function.__globals__
    record = {"restart_motion": False, "restart_api": False, "commit": "a" * 40}
    path = tmp_path / "preview.json"
    path.write_text(json.dumps(record))

    def failed_restart(command, **_kwargs):
        assert json.loads(path.read_text())["restart_motion"] is True
        assert command == ["sudo", "-n", "systemctl", "restart", "motion-executor.service"]
        raise RuntimeError("inert restart failed")

    monkeypatch.setitem(namespace, "motion_update_preflight", lambda: None)
    monkeypatch.setitem(namespace, "run", failed_restart)
    with pytest.raises(RuntimeError, match="inert restart failed"):
        function(tmp_path, path, {"restart_motion": True}, record, False)
    assert json.loads(path.read_text())["commit"] == record["commit"]


def test_failed_checkout_restores_previous_record_before_service_recovery(deploy, monkeypatch, tmp_path):
    function = deploy["_restore_preview_failure"]
    namespace = function.__globals__
    path = tmp_path / "preview.json"
    path.write_text('{"commit": "new"}')
    previous = {"commit": "old"}
    events = []

    def recovered(command, **_kwargs):
        assert json.loads(path.read_text()) == previous
        events.append(command)

    monkeypatch.setitem(namespace, "git", lambda *_args: "old")
    monkeypatch.setitem(namespace, "run", recovered)
    monkeypatch.setitem(namespace, "restart_api", lambda: events.append("api"))
    monkeypatch.setitem(namespace, "resume_display", lambda active: events.append(("display", active)))
    function(tmp_path, path, {"restart_motion": True}, previous, "old", True, True)
    assert events == [["sudo", "-n", "systemctl", "start", "motion-executor.service"], "api", ("display", True)]


def test_boot_migration_records_intent_before_inert_backend_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(systemd_reconcile, "UNIT_CATALOG", {"example.service": {}})
    monkeypatch.setattr(systemd_reconcile, "BOOT_UNITS", ("example.service",))
    monkeypatch.setattr(
        systemd_reconcile.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(stdout="disabled")
    )
    manifest = {"units": [], "boot_changes": []}

    def fail(*args):
        recorded = json.loads((tmp_path / "manifest.json").read_text())
        assert recorded["boot_changes"] == [{"unit": "example.service", "previous": "disabled", "action": "enable"}]
        assert args == ("--no-reload", "enable", "example.service")
        raise OSError("inert backend failed")

    monkeypatch.setattr(systemd_reconcile, "_systemctl", fail)
    with pytest.raises(OSError, match="inert backend failed"):
        systemd_reconcile._consolidate_boot([], tmp_path, manifest)


def test_timed_start_refuses_existing_goal_before_requesting_operator_file():
    client = SimpleNamespace(catalog=lambda: {"features": [{"name": "moving", "can_move": True, "requested": True}]})
    args = SimpleNamespace(feature="moving", seconds=1, control_file=Mock())
    with pytest.raises(ValueError, match="timed_session_requires_unrequested_goal"):
        robot_ctl._start_body(client, args, {})
    args.control_file.stat.assert_not_called()


@pytest.mark.parametrize(
    "kind,action,name,path,method",
    [
        ("service", "logs", "name/unit", "/api/services/name%2Funit/logs", "GET"),
        ("service", "restart", "name/unit", "/svc/name%2Funit", "POST"),
        ("face", "status", None, "/api/face-studio/runtime", "GET"),
        ("camera", "stop", None, "/api/resource/camera", "POST"),
    ],
)
def test_resource_route_retains_encoded_names_and_read_only_methods(kind, action, name, path, method):
    assert resource_ctl._route(SimpleNamespace(kind=kind, action=action, name=name)) == (path, method)


@pytest.mark.parametrize(
    "line,expected",
    [
        ("ExecStart=/usr/bin/env /usr/bin/python3 /home/pi/robot/script.py", ["/usr/bin/python3"]),
        ("ExecStart=/bin/bash -lc 'python3 scripts/passive.py'", ["scripts/passive.py"]),
        ("ExecStart=-/usr/bin/flock -n /tmp/lock /usr/bin/python3", ["/usr/bin/python3"]),
        ("ExecStart=/usr/bin/env https://example.invalid/a 2>/tmp/error /opt/tool", ["/opt/tool"]),
    ],
)
def test_unit_parser_retains_wrapper_option_and_redirect_handling(line, expected):
    module = runpy.run_path(str(ROOT / "scripts/diag_validate-systemd-paths.py"))
    assert module["parse_exec_line"](line) == expected
