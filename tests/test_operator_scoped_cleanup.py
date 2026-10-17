"""No BUS: cleanup uses only captured authority and an injected scoped callback."""

from types import SimpleNamespace

from services.core.operator_cleanup import stop_override


def manager(state):
    calls = []
    return SimpleNamespace(
        safety_status=lambda: dict(state),
        producer_status=lambda _unit: {"operator_control_version": 1},
        safety_scoped_stop=lambda owner, generation: calls.append((owner, generation))
        or {"ok": True, "confirmed": True},
    ), calls


def state(generation="resumed", owner="navigation", operation="resume"):
    return {
        "generation": generation,
        "owner": owner,
        "state": "ARMED",
        "operator_control": {"version": 1, "state": "active", "operation_id": operation},
    }


def test_explicit_stop_targets_current_resume_generation_not_original_claim():
    current = state()
    instance, calls = manager(current)
    revoke = stop_override(instance, "s14_venom_navigation", False)
    assert revoke("navigation")["ok"]
    assert calls == [("navigation", "resumed")]


def test_delayed_cleanup_cannot_revoke_newer_manual_generation():
    current = state()
    instance, calls = manager(current)
    revoke = stop_override(instance, "s14_venom_navigation", False)
    current.update(state(generation="manual", owner="manual", operation="correction"))
    assert revoke("navigation")["superseded"]
    assert calls == []


def test_manual_holding_same_post_stop_generation_is_not_revoked():
    current = state(generation="post-stop", owner=None, operation=None)
    current["state"] = "DISARMED"
    instance, calls = manager(current)
    revoke = stop_override(instance, "s14_venom_navigation", False)
    # ARM can preserve the DISARMED generation. Owner/state still separate it.
    current.update(state(generation="post-stop", owner="manual", operation="new-arm"))
    assert revoke("navigation")["superseded"]
    assert calls == []


def test_old_operation_with_same_generation_does_not_stop_new_operation():
    current = state()
    instance, calls = manager(current)
    revoke = stop_override(instance, "s14_venom_navigation", False)
    current.update(state(operation="later"))
    assert revoke("navigation")["superseded"]
    assert calls == []
