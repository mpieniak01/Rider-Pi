from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest
from flask import Flask

from services.api_core import version_api

COMMIT = "a1b2c3d" + "0" * 33


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(version_api, "_cache", None)
    monkeypatch.setattr(version_api, "_cache_until", 0)
    app = Flask(__name__)
    app.register_blueprint(version_api.bp)
    return app.test_client()


def fake_git(monkeypatch, *, dirty=False, detached=False):
    calls = []

    def run(command, **options):
        assert command[:3] == ["git", "-C", str(version_api.REPO_ROOT)]
        assert options["timeout"] == version_api.GIT_TIMEOUT
        assert options["check"] is False
        args = command[3:]
        calls.append(args)
        values = {
            "rev-parse": COMMIT,
            "symbolic-ref": "main",
            "status": " M tracked.py\n" if dirty else "",
            "log": "fix(ui): dashboard\n",
        }
        return SimpleNamespace(returncode=1 if detached and args[0] == "symbolic-ref" else 0, stdout=values[args[0]])

    monkeypatch.setattr(version_api.subprocess, "run", run)
    return calls


def test_version_contract_and_repo_source(client, monkeypatch, tmp_path):
    calls = fake_git(monkeypatch, dirty=True)
    monkeypatch.chdir(tmp_path)
    response = client.get("/api/status/version")
    data = response.get_json()
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert data["available"] is True
    assert data["branch"] == "main"
    assert data["commit"] == COMMIT[:7]
    assert data["dirty"] is True
    assert data["message"] == "fix(ui): dashboard"
    assert isinstance(data["ts"], (float, int))
    assert len(calls) == 4


def test_detached_head_is_not_main(client, monkeypatch):
    fake_git(monkeypatch, detached=True)
    data = client.get("/api/status/version").get_json()
    assert data["available"] is True
    assert data["branch"] == "HEAD"
    assert data["dirty"] is False


def test_cache_expires_and_return_value_is_not_shared(client, monkeypatch):
    calls = fake_git(monkeypatch)
    clock = [100.0]
    monkeypatch.setattr(version_api.time, "monotonic", lambda: clock[0])
    initial = version_api.get_version_info()
    initial["branch"] = "tampered"
    clock[0] += 59
    assert client.get("/api/status/version").get_json()["branch"] == "main"
    assert len(calls) == 4
    clock[0] += 2
    assert client.get("/api/status/version").status_code == 200
    assert len(calls) == 8


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError(), subprocess.TimeoutExpired("git", 1), subprocess.CalledProcessError(128, "git")],
)
def test_unavailable_metadata_is_nonfatal_and_cached(client, monkeypatch, error):
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        raise error

    monkeypatch.setattr(version_api.subprocess, "run", run)
    for _ in range(2):
        response = client.get("/api/status/version")
        assert response.status_code == 200
        data = response.get_json()
        assert data["available"] is False
        assert data["commit"] is None
        assert data["branch"] == "unknown"
    assert len(calls) == 1


def test_invalid_commit_is_not_presented_as_a_version(client, monkeypatch):
    monkeypatch.setattr(
        version_api.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="bad")
    )
    assert client.get("/api/status/version").get_json()["available"] is False


def test_git_exit_error_is_not_a_server_error(client, monkeypatch):
    monkeypatch.setattr(
        version_api.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=128, stdout="")
    )
    assert client.get("/api/status/version").get_json()["available"] is False


def test_version_endpoint_rejects_writes_without_running_git(client, monkeypatch):
    calls = fake_git(monkeypatch)
    assert client.post("/api/status/version", json={}).status_code == 405
    assert calls == []
