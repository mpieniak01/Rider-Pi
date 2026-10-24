"""Visual references persist independently of navigation or hardware."""

import copy
import json

import pytest

from services import image_reference as ref


@pytest.fixture
def values(tmp_path, monkeypatch):
    monkeypatch.setenv("RIDER_IMAGE_REFERENCE", str(tmp_path / "image-reference.json"))
    return {
        "visible": True,
        "frame_size": [320, 240],
        "track_width_cm": 16.0,
        "robot_width_cm": 11.5,
        "camera_height_cm": 14.0,
        "reference_pose": "lowest",
        "left_edge": [[0.39, 0.65], [0.29, 1.0]],
        "right_edge": [[0.58, 0.65], [0.74, 1.0]],
        "markers": [[18.0, 1.0], [20.0, 227 / 240], [40.0, 181 / 240], [60.0, 160 / 240]],
    }


def test_persist_cas_and_restore_without_navigation_policy(values, tmp_path):
    assert ref.snapshot()["values"] is None
    saved = ref.configure({"revision": 0, "values": values})
    assert saved == ref.snapshot()
    assert saved["revision"] == 1 and saved["purpose"] == "visual_reference_only"
    assert not (tmp_path / "navigation_config.json").exists()
    with pytest.raises(ValueError, match="image_reference_conflict"):
        ref.configure({"revision": 0, "values": values})
    assert json.loads(ref.path().read_text()) == saved
    values["track_width_cm"] = 21
    assert ref.snapshot()["values"]["track_width_cm"] == 16


@pytest.mark.parametrize(
    "key,value",
    [
        ("track_width_cm", True),
        ("track_width_cm", 10**400),
        ("camera_height_cm", -(10**400)),
        ("camera_height_cm", float("nan")),
        ("robot_width_cm", 17),
        ("frame_size", [0, 240]),
        ("markers", [[20, 0.7], [40, 0.8]]),
        ("markers", [[20, 0.7], [20, 0.5]]),
        ("left_edge", [[0.8, 0.65], [0.8, 1.0]]),
        ("right_edge", [[0.6, 0.5], [0.7, 1.0]]),
        ("reference_pose", "any"),
    ],
)
def test_invalid_measurement_never_persists(values, key, value):
    invalid = copy.deepcopy(values)
    invalid[key] = value
    with pytest.raises(ValueError, match="image_reference_invalid"):
        ref.configure({"revision": 0, "values": invalid})
    assert not ref.path().exists()


def test_policy_fields_are_not_accepted_as_visual_settings(values):
    values["verified"] = True
    with pytest.raises(ValueError, match="image_reference_invalid"):
        ref.configure({"revision": 0, "values": values})


@pytest.mark.parametrize(
    "stored", [[], 3, {"version": True, "revision": 1, "values": {}, "purpose": "visual_reference_only"}]
)
def test_invalid_local_file_is_not_presented_as_calibration(values, stored):
    ref.path().write_text(json.dumps(stored))
    with pytest.raises(ValueError, match="image_reference_invalid"):
        ref.snapshot()


def test_http_handler_reports_cas_and_validation_without_motion(values):
    from flask import Flask

    from services.api_core.navigation_api import image_reference_handler

    app = Flask(__name__)
    app.add_url_rule("/api/navigation/image-reference", view_func=image_reference_handler, methods=["GET", "POST"])
    client = app.test_client()
    assert client.get("/api/navigation/image-reference").json["values"] is None
    saved = client.post("/api/navigation/image-reference", json={"revision": 0, "values": values})
    assert saved.status_code == 200 and saved.json["purpose"] == "visual_reference_only"
    oversized = {**values, "track_width_cm": 10**400}
    rejected = client.post("/api/navigation/image-reference", json={"revision": 1, "values": oversized})
    assert rejected.status_code == 422
    assert ref.snapshot()["values"] == values
    assert client.post("/api/navigation/image-reference", json={"revision": 0, "values": values}).status_code == 409
    assert client.post("/api/navigation/image-reference", json={"revision": True, "values": values}).status_code == 422


def test_negotiated_save_confirms_persistence_and_readback(values):
    from flask import Flask

    from services.api_core.http_contract import install
    from services.api_core.navigation_api import image_reference_handler

    app = Flask(__name__)
    app.add_url_rule("/api/navigation/image-reference", view_func=image_reference_handler, methods=["GET", "POST"])
    install(app, after_request=True)
    client = app.test_client()
    headers = {"Accept": "application/vnd.rider.api+json;version=1"}
    saved = client.post("/api/navigation/image-reference", json={"revision": 0, "values": values}, headers=headers)
    assert saved.status_code == 200 and saved.json["ok"] is True
    assert saved.json["meta"]["contract_id"] == "rider.navigation_loop"
    assert saved.json["operation"]["ack_kind"] == "configuration_persisted"
    assert saved.json["operation"]["actuation"] is False
    restored = client.get("/api/navigation/image-reference", headers=headers)
    assert restored.json["data"] == saved.json["data"] == ref.snapshot()
    conflict = client.post("/api/navigation/image-reference", json={"revision": 0, "values": values}, headers=headers)
    assert conflict.status_code == 409 and conflict.json["ok"] is False
