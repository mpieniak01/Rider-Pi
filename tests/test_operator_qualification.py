"""No network, hardware or BUS: local fresh-frame qualification only."""

from apps.compute.qualification import Qualification

POLICY = {"revision": 4, "decision_budget_ms": 300, "model_sha256": "a" * 64}


def reply(sequence, **updates):
    return {
        "protocol_version": 1,
        "run_id": "new",
        "frame_id": str(sequence),
        "sequence": sequence,
        "config_revision": 4,
        "model_sha256": "a" * 64,
        "state": "clear",
        "action": "go",
        "valid_for_ms": 150,
        **updates,
    }


def test_cached_high_clear_count_cannot_bypass_three_new_frames():
    evidence = Qualification(POLICY, "new", 10)
    assert not evidence.accept(reply(1, clear_count=900), "1", 1, 10.01, 10.02)
    assert not evidence.accept(reply(2), "2", 2, 10.02, 10.03)
    assert evidence.accept(reply(3), "3", 3, 10.03, 10.04)


def test_pre_resume_duplicate_expired_wrong_model_and_obstacle_reset_count():
    for decision, frame, seq, captured, now in [
        (reply(2), "2", 2, 9.99, 10.01),
        (reply(1), "1", 1, 10.01, 10.02),
        (reply(2), "2", 2, 10.01, 10.4),
        (reply(2, model_sha256="b" * 64), "2", 2, 10.02, 10.03),
        (reply(2, state="obstacle"), "2", 2, 10.02, 10.03),
        (reply(2, run_id="old"), "2", 2, 10.02, 10.03),
    ]:
        evidence = Qualification(POLICY, "new", 10)
        assert not evidence.accept(reply(1), "1", 1, 10.01, 10.02)
        assert not evidence.accept(decision, frame, seq, captured, now)
        assert evidence.count == 0


def test_stream_session_change_starts_new_consecutive_series():
    evidence = Qualification(POLICY, "new", 10)
    assert not evidence.accept(reply(1, source={"camera_session": "a"}), "1", 1, 10.01, 10.02)
    assert not evidence.accept(reply(2, source={"camera_session": "b"}), "2", 2, 10.02, 10.03)
    assert evidence.count == 1


def test_configured_evidence_is_required_for_each_qualification_frame():
    evidence = Qualification(
        POLICY, "new", 10, validate_evidence=lambda decision: decision.get("verified_ground") is True
    )
    assert not evidence.accept(reply(1, verified_ground=True), "1", 1, 10.01, 10.02)
    assert not evidence.accept(reply(2), "2", 2, 10.02, 10.03)
    assert evidence.count == 0


def test_pipeline_revision_change_restarts_three_frame_series():
    evidence = Qualification(POLICY, "new", 10)
    assert not evidence.accept(reply(1, source={"pipeline_revision": 1}), "1", 1, 10.01, 10.02)
    assert not evidence.accept(reply(2, source={"pipeline_revision": 2}), "2", 2, 10.02, 10.03)
    assert evidence.count == 1
