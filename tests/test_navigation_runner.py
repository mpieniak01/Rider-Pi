import time
from types import SimpleNamespace

import pytest

from apps.compute import navigation as module
from common.service_catalog import DEFAULT_REGISTRY, UNIT_CATALOG
from services.navigation_config import DEFAULT


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    policy = {**DEFAULT, "mode": "drive", "verified": True, "calibration_id": "trial", "model_sha256": "a" * 64}
    selection = {
        "id": "venom",
        "revision": 1,
        "device_id": "pi",
        "token": "fixture-token",
        "url": "http://127.0.0.1:8800",
        "tasks": [],
    }
    safety = {
        "remote_decision_deadline_supported": True,
        "can_move": True,
        "owner": "navigation",
        "generation": "gen",
        "last_seq": 0,
        "manual_settings": {"revision": 3},
        "calibration": {"profile_digest": "accepted"},
    }
    intent = {"generation": "gen", "request_id": "intent", "seq": 1, "settings_revision": 3}
    commands = []
    monkeypatch.setattr(module.navigation_config, "snapshot", lambda: dict(policy))
    monkeypatch.setattr(module, "selected_executor", lambda: dict(selection))
    monkeypatch.setattr(module, "read_status", lambda: dict(safety))
    monkeypatch.setattr(module, "read_service_intent", lambda *_: dict(intent))
    monkeypatch.setattr(module, "write_intent_status", lambda *a, **kw: True)
    monkeypatch.setenv("RIDER_NAVIGATION_STATUS", str(tmp_path / "status.json"))

    def submit(data):
        commands.append(data)
        return {"ok": True}, 200

    monkeypatch.setattr(module, "submit_control", submit)
    return policy, selection, safety, intent, commands


def test_catalog_no_local_detector_and_separate_owner():
    drive = DEFAULT_REGISTRY["s14_venom_navigation"]
    observe = DEFAULT_REGISTRY["s15_venom_perception"]
    assert drive.can_move and drive.control_owner == "navigation"
    assert not observe.can_move
    assert "rider-vision.service" not in drive.members
    assert "rider-obstacle.service" not in drive.members
    assert UNIT_CATALOG["rider-venom-navigation.service"]["motion_owner"] == "navigation"
    assert UNIT_CATALOG["rider-venom-perception.service"]["can_move"] is False


def test_capture_decision_motion_then_transport_loss_stops(isolated):
    _, _, _, _, commands = isolated
    count = [0]

    class Source:
        closed = False

        def recv(self, _):
            count[0] += 1
            return {
                "input_id": "f" + str(count[0]),
                "captured_at": time.time(),
                "content_type": "image/jpeg",
                "data": b"fixture",
            }

        def close(self):
            self.closed = True

    source = Source()

    def remote(meta, *_):
        if meta["sequence"] == 4:
            raise TimeoutError()
        return {
            **{k: meta[k] for k in ("protocol_version", "run_id", "frame_id", "sequence", "config_revision")},
            "action": "go" if meta["sequence"] == 3 else "stop",
            "state": "clear",
            "valid_for_ms": 150,
            "clear_count": meta["sequence"],
            "model_sha256": "a" * 64,
        }

    runner = module.NavigationRunner(source_factory=lambda: source, request=remote)
    assert runner.run() == 2
    assert source.closed
    assert len([x for x in commands if x["action"] == "move"]) == 1
    assert commands[-1]["action"] == "stop"
    assert runner.lease.latched


def test_observe_never_sends_motion_even_with_forged_go(isolated):
    _, _, _, _, commands = isolated
    runner = module.NavigationRunner(observe_only=True)
    runner.drive = lambda *_: pytest.fail("observation actuated")
    runner.stop()
    assert commands == []
    assert runner._authority() is False


def test_manual_takeover_is_not_disarmed_by_old_runner(isolated):
    _, _, safety, _, commands = isolated
    runner = module.NavigationRunner()
    runner._authority()
    safety.update(owner="manual", generation="new")
    runner.stop()
    with pytest.raises(module.ComputeError):
        runner._authority()
    assert commands == []


def test_expired_generation_or_intent_cannot_be_adopted(isolated):
    _, _, safety, intent, _ = isolated
    runner = module.NavigationRunner()
    runner._authority()
    intent["request_id"] = "different"
    with pytest.raises(module.ComputeError):
        runner._authority()
    intent["request_id"] = "intent"
    safety["generation"] = "different"
    with pytest.raises(module.ComputeError):
        runner._authority()


def test_failed_claim_and_motion_rejection_stop(isolated, monkeypatch):
    runner = module.NavigationRunner()
    monkeypatch.setattr(module, "write_intent_status", lambda *a, **kw: False)
    with pytest.raises(module.ComputeError):
        runner._authority()
    monkeypatch.setattr(module, "write_intent_status", lambda *a, **kw: True)
    monkeypatch.setattr(module, "submit_control", lambda *_: ({"ok": False}, 409))
    with pytest.raises(module.ComputeError):
        runner.drive(0.1, 0.1)


def test_redirects_cannot_forward_device_token():
    with pytest.raises(module.ComputeError):
        module.NoRedirect().redirect_request(None, None, None, None, None, None)


def test_missing_executor_fails_before_camera(monkeypatch):
    monkeypatch.setattr(module, "selected_executor", lambda: None)
    monkeypatch.setattr(module.navigation_config, "snapshot", lambda: dict(DEFAULT))
    with pytest.raises(module.ComputeError):
        module.NavigationRunner()


def test_oversized_response_rejected(isolated, monkeypatch):
    runner = module.NavigationRunner()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, _):
            return b"x" * 16385

    monkeypatch.setattr(
        module.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=lambda *a, **kw: Response())
    )
    with pytest.raises(module.ComputeError):
        runner._request({}, b"fixture", "image/jpeg")


def test_calibration_revision_change_ends_run(isolated):
    _, _, safety, _, _ = isolated
    runner = module.NavigationRunner()
    runner._authority()
    safety["manual_settings"] = {"revision": 4}
    with pytest.raises(module.ComputeError, match="navigation_settings_stale"):
        runner._authority()


def test_shared_config_api_confirms_persistence_and_reports_stale_status(tmp_path, monkeypatch):
    from flask import Flask

    from services.api_core import http_contract, rider_routes

    monkeypatch.setenv("RIDER_NAVIGATION_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("FEATURE_STATE_PATH", str(tmp_path / "feature.json"))
    monkeypatch.setenv("RIDER_COMPUTE_CONFIG", str(tmp_path / "compute.json"))
    monkeypatch.setenv("RIDER_NAVIGATION_STATUS", str(tmp_path / "status.json"))
    app = Flask(__name__)
    http_contract.install(app, after_request=True)
    rider_routes.register_compute(app)
    with app.test_client() as client:
        headers = {"Accept": "application/vnd.rider.api+json;version=1"}
        assert client.get("/api/navigation/status", headers=headers).json["data"]["stale"]
        result = client.post("/api/navigation/config", json={"revision": 0, "values": {"speed": 0.12}}, headers=headers)
        assert result.status_code == 200
        assert result.json["data"]["persisted"] is True
        assert result.json["operation"]["confirmed"] is True
        assert result.json["data"]["config"]["revision"] == 1
        assert (
            client.post("/api/navigation/config", json={"revision": 0, "values": {}}, headers=headers).status_code
            == 409
        )


def test_changed_speed_invalidates_old_stopping_zone(tmp_path, monkeypatch):
    from services import navigation_config as config

    monkeypatch.setenv("RIDER_NAVIGATION_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("FEATURE_STATE_PATH", str(tmp_path / "features.json"))
    initial = config.configure(
        {
            "revision": 0,
            "values": {"mode": "drive", "verified": True, "calibration_id": "trial1", "model_sha256": "a" * 64},
        }
    )
    assert initial["mode"] == "drive"
    changed = config.configure({"revision": 1, "values": {"speed": 0.12}})
    assert changed["mode"] == "observe"
    assert changed["verified"] is False


@pytest.mark.parametrize(
    "code, expected",
    [
        ("navigation_configuration_conflict", 409),
        ("navigation_stop_goals_first", 409),
        ("navigation_speed_invalid", 400),
    ],
)
def test_navigation_configuration_api_errors(monkeypatch, code, expected):
    from flask import Flask

    from services.api_core import navigation_api

    app = Flask(__name__)

    def fail(_):
        raise ValueError(code)

    monkeypatch.setattr(navigation_api.navigation_config, "configure", fail)
    with app.test_request_context("/api/navigation/config", method="POST", json={}):
        response, status = navigation_api.config_handler()
    assert status == expected and response.json["error"] == code


def test_navigation_configuration_api_read_and_persistence_failure(monkeypatch):
    from flask import Flask

    from services.api_core import navigation_api

    app = Flask(__name__)
    monkeypatch.setattr(navigation_api.navigation_config, "snapshot", lambda: dict(DEFAULT))
    with app.test_request_context("/api/navigation/config", method="GET"):
        response, status = navigation_api.config_handler()
    assert status == 200 and response.json["mode"] == "observe"

    def fail(_):
        raise OSError("fixture")

    monkeypatch.setattr(navigation_api.navigation_config, "configure", fail)
    with app.test_request_context("/api/navigation/config", method="POST", json={}):
        response, status = navigation_api.config_handler()
    assert status == 503 and response.json["error"] == "navigation_persistence_failed"


@pytest.mark.parametrize("payload", ['[]', '{"observed_at": NaN}', "x" * 16385])
def test_navigation_status_invalid_file_is_stale(monkeypatch, tmp_path, payload):
    from flask import Flask

    from services.api_core.navigation_api import status_handler

    target = tmp_path / "state.json"
    target.write_text(payload)
    monkeypatch.setenv("RIDER_NAVIGATION_STATUS", str(target))
    with Flask(__name__).app_context():
        response, code = status_handler()
    assert code == 200 and response.json["stale"] is True
