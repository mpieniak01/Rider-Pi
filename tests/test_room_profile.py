"""Room policy is opt-in and cannot silently change released presets."""

import pytest

from services.navigation_profiles import (
    catalog,
    parameters,
    policy_digest,
    validate_behavior,
)

OLD_DIGESTS = {
    "legacy-r1": "ac4ead83271061bc5c39ad545cf0d08419ecde42d648f127b7e7836d1fb5765f",
    "cautious-r1": "0e0421d0b8c17f7b4911c39411a6403be074f62add849d5da383691fb01ffdf5",
    "cautious-r2": "29e40f6a514bb5ab1cc95b401c017311fbf723eaf5f922e180fc60d921a86044",
    "balanced-r1": "5189adbd89aa0b8427d31d684e5742b2be3e90210fd88d8917bc778de1539e09",
    "balanced-r2": "8952549c1e8359e7133f7ff72ee03c0129384a9ccf72c9066332b9ff94aa27bb",
    "fluid-r1": "36b9f0adf60f1d3351caf99ce0349bc93d3355d8c4b032b67e005a73b7080ba6",
    "fluid-r2": "912b3ba5451c3c46b9e05dbd713ca4707d929ac839133d7a2bea1b2ef9e56869",
}


def choice(name="room_fluid", revision=2, **overrides):
    value = {"version": 1, "profile_id": name, "profile_revision": revision}
    if overrides:
        value["overrides"] = overrides
    return value


@pytest.mark.parametrize("identity,digest", OLD_DIGESTS.items())
def test_released_policy_digests_remain_pinned(identity, digest):
    name, revision = identity.rsplit("-r", 1)
    assert policy_digest(choice(name, int(revision))) == digest


def test_room_preset_requires_explicit_selection_and_enables_object_assessment():
    current = catalog(choice("fluid", 1))
    assert current["active"] == choice("fluid", 1)
    room = next(row for row in current["profiles"] if row["id"] == "room_fluid")
    assert room["profile_revision"] == 2
    values = parameters(choice())
    assert values["object_policy_enabled"] is True
    assert values["object_tracking_enabled"] is True
    assert values["obstacle_support_frames"] == 2
    assert values["obstacle_window_frames"] == 3
    assert values["thin_span_fraction"] == 1.0
    assert "object_policy_enabled" not in parameters(choice("fluid"))


@pytest.mark.parametrize(
    "selection",
    [
        choice(revision=1),
        choice("fluid", object_policy_enabled=True),
        choice("balanced", object_policy_enabled=False),
        choice(object_tracking_enabled=False),
    ],
)
def test_room_activation_cannot_leak_into_an_old_preset(selection):
    with pytest.raises(ValueError):
        validate_behavior(selection)


def test_operator_can_compare_without_object_policy_and_restore_preset():
    custom = choice(
        object_policy_enabled=False,
        object_tracking_enabled=False,
        obstacle_support_frames=3,
    )
    values = parameters(custom)
    assert values["object_policy_enabled"] is False
    assert values["obstacle_support_frames"] == 3
    assert parameters(choice())["object_policy_enabled"] is True
    assert policy_digest(custom) != policy_digest(choice())
