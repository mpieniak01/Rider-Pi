"""Input-region persistence and preparation capability remain explicit."""

import copy

import pytest

from apps.compute.client import ComputeError
from apps.compute.stream_prepare import _require_input_region
from services import navigation_config
from services.model_input import RECOMMENDED, validate_input_region


def config():
    """Build an isolated DA2 policy with the recommended input region."""
    value = copy.deepcopy(navigation_config.DEFAULT)
    value["perception"]["engine"] = "depth_plane"
    value["perception"]["input_region"] = copy.deepcopy(RECOMMENDED)
    return value


def test_recommended_input_is_valid_without_migrating_old_policies():
    """Verify optional crop defaults never migrate a legacy policy during validation."""
    old = copy.deepcopy(navigation_config.DEFAULT)
    navigation_config.validate(old)
    assert "input_region" not in old["perception"]
    assert navigation_config.validate(config())["perception"]["input_region"] == RECOMMENDED


@pytest.mark.parametrize("bounds", [[0, 0.9, 1, 1], [0.4, 0.4, 0.6, 1]])
def test_crop_must_cover_reference_and_decision(bounds):
    """Reject crops that omit the assessed corridor or its floor reference."""
    value = config()
    value["perception"]["input_region"]["bounds"] = bounds
    with pytest.raises(ValueError, match="excludes_reference"):
        navigation_config.validate(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        {"version": True, "bounds": [0, 0, 1, 1]},
        {"version": 2, "bounds": [0, 0, 1, 1]},
        {"version": 1, "bounds": [False, 0, 1, 1]},
        {"version": 1, "bounds": [0, float("nan"), 1, 1]},
    ],
)
def test_malformed_regions_are_rejected(value):
    """Reject invalid versions, booleans and non-finite region coordinates."""
    with pytest.raises(ValueError, match="input_region_invalid"):
        validate_input_region(value)


@pytest.mark.parametrize("status", [{}, {"input_region_version": True}, {"input_region_version": 2}])
def test_preparation_requires_real_host_capability_before_arm(status):
    """Require a strict supported version before accepting a crop-aware host."""
    with pytest.raises(ComputeError, match="input_region_update_required"):
        _require_input_region(status, 1)
    _require_input_region(status, None)
    _require_input_region({"input_region_version": 1}, 1)
