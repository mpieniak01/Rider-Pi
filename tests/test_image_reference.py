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
