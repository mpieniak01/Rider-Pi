"""Invalid temporal actions are rejected before inspecting numeric evidence."""

from services.navigation_behavior import reply_valid
from services.navigation_profiles import DEFAULT_BEHAVIOR, policy_digest


def test_mismatched_temporal_action_rejected_before_oversized_speed_factor():
    behavior = {**DEFAULT_BEHAVIOR, "profile_id": "balanced"}
    config = {"behavior": behavior}
    decision = {
        "behavior": behavior,
        "effective_policy_sha256": policy_digest(behavior),
        "action": "go",
        "state": "clear",
        "temporal": {
            "version": 1,
            "action": "slow",
            "near_guard_clear": True,
            "evidence_frames": 3,
            "speed_factor": 10**1000,
        },
    }

    assert reply_valid(config, decision) is False
