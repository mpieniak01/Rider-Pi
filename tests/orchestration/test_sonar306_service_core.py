"""Service-stage characterizations use fake units, passive journals and no external I/O."""

import json
import sys
from types import SimpleNamespace

import pytest
from test_task_lifecycle import World

from common import service_action_guard
from common.service_catalog import DEFAULT_REGISTRY
from services.core import camera_state, feature_admin, goal_journal, service_permissions
from services.core.features import FeatureManager, NullPublisher


def test_start_dependency_failure_does_not_stage_or_run(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    manager.dependency_check = lambda *_: ['missing-fixture']
    result = manager.set_feature('face_tracking', True)
    assert result['error'] == 'runtime_dependencies_missing'
    assert world.actions == []
    assert manager._pending == {}
    assert manager._intents == {}
    assert manager._states['s3_follow_me_face'] == 'failed'


def test_start_generation_change_revokes_before_member_rollback(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    original = manager.runner

    def changed(unit, action):
        result = original(unit, action)
        if unit == 'rider-tracking-controller.service':
            world.safety['generation'] = 'new-generation'
        return result

    manager.runner = changed
    result = manager.set_feature('face_tracking', True)
    assert result['error'] == 'operator_generation_changed'
    stop_index = world.actions.index(('control', 'stop'))
    assert all(action != 'stop' for _, action in world.actions[:stop_index])
    assert manager._pending == {}
    assert manager._intents == {}
    assert not any(world.active.intersection({'rider-tracking-controller.service', 'rider-followme.target'}))


def test_stop_unconfirmed_keeps_ownership_and_skips_unit_stop(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.set_feature('face_tracking', True)['ok']
    world.actions.clear()
    world.stop_confirmed = False
    result = manager.set_feature('face_tracking', False)
    assert result['error'] == 'stop_unconfirmed'
    assert world.actions == [('control', 'stop')]
    assert 's3_follow_me_face' in manager._requested
    assert manager._states['s3_follow_me_face'] == 'partial'


def test_feature_dispatch_exception_always_clears_pending_intent(tmp_path, monkeypatch):
    manager = World().manager(tmp_path)
    manager._pending['s2_camera_preview'] = {}
    manager._intents['s2_camera_preview'] = {'request_id': 'pending'}

    def fail(*_):
        raise ValueError('fake start failure')

    monkeypatch.setattr(manager, '_start', fail)
    with pytest.raises(ValueError, match='fake start failure'):
        manager._apply_feature_change('s2_camera_preview', True, {}, None, None)
    assert 's2_camera_preview' not in manager._pending
    assert 's2_camera_preview' not in manager._intents


def test_admin_profile_persistence_failure_restores_previous_domain(tmp_path, monkeypatch):
    world = World()
    manager = world.manager(tmp_path)
    monkeypatch.setattr(manager, '_persist_state', lambda: False)
    result = manager.service_action('rider-voice-web.service', 'start', {'domain': 'text'})
    assert result['error'] == 'profile_journal_unavailable'
    assert manager._service_domains == {}
    assert world.actions == []


def test_admin_motion_intent_journal_failure_does_not_start(tmp_path, monkeypatch):
    world = World()
    manager = world.manager(tmp_path)
    monkeypatch.setattr(manager, '_intent_permission', lambda _: None)
    monkeypatch.setattr(manager, '_persist_state', lambda: False)
    result = manager.service_action(
        'rider-tracking-controller.service', 'start', {'generation': world.safety['generation']}
    )
    assert result['error'] == 'control_journal_unavailable'
    assert manager._admin_intents == {}
    assert world.actions == []


def test_admin_changed_generation_revokes_before_stop_and_preserves_failed_rollback(tmp_path, monkeypatch):
    world = World()
    manager = world.manager(tmp_path)
    unit = 'rider-tracking-controller.service'
    manager._admin_intents[unit] = {'generation': 'old'}
    world.active.add(unit)
    world.stop_confirmed = False
    result = manager._verify_admin_start(
        unit, 'start', {'generation': 'old'}, {'motion_owner': 'follow_me'}, True, {'ok': True}
    )
    assert result['error'] == 'operator_generation_changed'
    assert world.actions == [('control', 'stop')]
    assert unit in manager._admin_units
    assert unit in manager._admin_intents


def test_producer_pid_mismatch_prevents_ready_projection(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    feature = DEFAULT_REGISTRY['s3_follow_me_face']
    manager._intents[feature.name] = {'generation': 'g', 'request_id': 'r'}
    manager.producer_status = lambda _: {
        'accepted': True,
        'active': True,
        'generation': 'g',
        'request_id': 'r',
        'pid': 5,
    }
    manager.status_fn = lambda _: {'pid': 6, 'active': 'active', 'load': 'loaded'}
    accepted, rows = manager._producer_readiness(feature, ('rider-tracking-controller.service',), {})
    assert not accepted
    assert rows[0]['matches_task'] is False


def test_resource_consumer_projection_keeps_voice_domains_separate(tmp_path):
    manager = World().manager(tmp_path)
    manager._admin_units.add('rider-voice-web.service')
    manager._service_domains['rider-voice-web.service'] = 'asr'
    result = manager.resource_consumers()
    assert result['mic'] == ['admin:rider-voice-web.service']
    assert 'speaker' not in result
    manager._service_domains['rider-voice-web.service'] = 'text'
    assert 'mic' not in manager.resource_consumers()


def test_journal_restore_ignores_motion_goal_and_mismatched_process(tmp_path, monkeypatch):
    world = World()
    manager = world.manager(tmp_path)
    manager._restored = False
    monkeypatch.setattr(goal_journal, 'boot_id', lambda: 'boot')
    manager._state_path.write_text(
        json.dumps(
            {
                'ownership_journal': {
                    'version': 1,
                    'boot_id': 'boot',
                    'goals': {'s3_follow_me_face': {}, 's2_camera_preview': {}},
                    'identities': {},
                    'managed': ['camera-capture@raw.service'],
                    'admin': ['rider-tracking-controller.service'],
                    'domains': {},
                }
            }
        )
    )
    goal_journal.restore(manager)
    assert 's3_follow_me_face' not in manager._requested
    assert 's2_camera_preview' not in manager._requested
    assert manager._managed_units == set()
    assert manager._admin_units == set()
    assert world.actions == []


@pytest.mark.parametrize(
    'stale,load,expected',
    [(True, 'not-found', 'unit_observation_unavailable'), (False, 'not-found', 'unit_unavailable')],
)
def test_permission_rejection_precedence(stale, load, expected):
    manager = SimpleNamespace(unit_consumers=lambda _: ['task'], safety_status=lambda: {})
    result = service_permissions.permissions('rider-api.service', {'load': load, 'stale': stale}, manager)
    assert result['stop']['reason'] == expected
    assert result['stop']['allowed'] is False


@pytest.mark.parametrize(
    'active,free,holders,expected',
    [('active', True, [], True), ('inactive', False, ['fake-owner'], True), ('inactive', True, [], False)],
)
def test_camera_activity_keeps_owner_process_and_frame_facts_separate(active, free, holders, expected):
    result = camera_state.snapshot(
        heartbeat={'ts': 900},
        owners={'free': free, 'holders': holders},
        status_fn=lambda _: {'active': active},
        now=1000,
    )
    assert result['on'] is expected
    assert result['data_fresh'] is False
    assert result['frame_observed_at'] == 900


def test_privileged_start_never_reads_safety_for_unknown_action(monkeypatch):
    fake = SimpleNamespace(read_status=lambda: pytest.fail("invalid action read safety"))
    monkeypatch.setitem(sys.modules, "services.safety_contract", fake)
    result = service_action_guard.check("rider-tracking-controller.service", "invalid")
    assert result["error"] == "unit_or_action_not_catalogued"


def test_privileged_empty_navigation_stop_uses_observation_without_global_stop(monkeypatch):
    fake = SimpleNamespace(
        read_status=lambda: {"state": "DISARMED", "owner": None, "ready": True, "stale": False},
        request_stop=lambda: pytest.fail("already disarmed target sent STOP"),
    )
    monkeypatch.setitem(sys.modules, "services.safety_contract", fake)
    result = service_action_guard.check("rider-venom-navigation.service", "stop")
    assert result == {"ok": True, "effects": ["already_disarmed_navigation_stop"]}
