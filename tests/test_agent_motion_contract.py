"""Authenticated agent control reaches only the in-memory motion fake."""

import json
import uuid

import pytest
from flask import Flask
from motion_fakes import command, executor as executor

from common.agent_control import signed_command, verify_command
from services import safety_contract
from services.api_core import agent_control_api, control_api, http_contract


@pytest.fixture
def operator(executor, monkeypatch):
    instance, clock = executor
    monkeypatch.setenv('RIDER_AGENT_TOKEN', 'unit-only-agent-token')
    instance.apply(
        command(
            instance,
            'arm',
            owner='manual',
            execution_context='panel',
            arming_mode='operator',
            operator_consent=True,
            operator_plan='Mock operator session',
        )
    )
    clock.now += 0.6
    return instance, clock


def body(instance, **overrides):
    data = {
        'generation': instance.gate.generation,
        'agent_epoch': instance.gate.agent_epoch,
        'seq': instance.gate.agent_last_seq + 1,
        'ts': instance.gate.wall_clock(),
        'ttl_ms': 500,
        'settings_revision': instance.controls['revision'],
        'request_id': uuid.uuid4().hex,
        'intent_id': uuid.uuid4().hex,
        'channel': 'chat',
        'direction': 'forward',
    }
    return {**data, **overrides}


def test_signed_agent_impulse_uses_shared_calibration_and_preserves_operator_arm(operator):
    instance, clock = operator
    generation = instance.gate.generation
    request = signed_command(body(instance))
    result = instance.apply(request)
    assert result['status'] == 'accepted' and result['source'] == 'agent'
    assert result['execution_context'] == 'agent' and result['channel'] == 'chat'
    from apps.motion.manual_settings import pulse

    expected = pulse(instance.controls, 'forward')
    assert result['requested']['vx'] == expected['vx']
    assert result['requested']['duration'] == expected['duration']
    instance.tick(0.02)
    clock.now += expected['duration'] + 0.01
    instance.tick(0.02)
    assert instance.gate.state == 'ARMED' and instance.gate.generation == generation
    assert instance.snapshot()['panel_motion_enabled'] is True
    assert instance.snapshot()['test_motion_enabled'] is False


def test_agent_does_not_consume_manual_sequence(operator):
    instance, _ = operator
    before = instance.gate.last_seq
    instance.apply(signed_command(body(instance)))
    assert instance.gate.last_seq == before
    assert instance.gate.agent_last_seq == 0
    assert instance.apply(command(instance))['status'] == 'accepted'


@pytest.mark.parametrize(
    'change',
    [
        {'direction': 'backward'},
        {'channel': 'voice'},
        {'agent_epoch': 'forged'},
        {'source': 'manual'},
        {'execution_context': 'panel'},
        {'authorized': True},
        {'vx': 1},
    ],
)
def test_agent_signature_or_boolean_forgery_never_changes_manual_intent(operator, change):
    instance, _ = operator
    agent = signed_command(body(instance))
    instance.apply(command(instance))
    before = list(instance.adapter.calls)
    generation = instance.gate.generation
    result = instance.apply({**agent, **change})
    assert result['status'] == 'rejected'
    assert instance.adapter.calls == before
    assert instance.gate.generation == generation and instance.gate.state == 'ARMED'


def test_manual_takeover_revokes_agent_epoch_and_late_agent_cannot_stop_manual(operator):
    instance, _ = operator
    late = signed_command(body(instance))
    first = signed_command(body(instance))
    assert instance.apply(first)['status'] == 'accepted'
    before_epoch = instance.gate.agent_epoch
    assert instance.apply(command(instance))['status'] == 'accepted'
    assert instance.gate.agent_epoch != before_epoch
    before = list(instance.adapter.calls)
    assert instance.apply(late)['status'] == 'rejected'
    assert instance.adapter.calls == before
    assert instance.pending['source'] == 'manual' and instance.gate.state == 'ARMED'


@pytest.mark.parametrize('first_agent', [False, True])
def test_manual_wins_both_received_batch_orders(operator, first_agent):
    instance, _ = operator
    agent = signed_command(body(instance))
    manual = command(instance)
    batch = [('motion.command', agent), ('motion.command', manual)]
    instance.process_batch(batch if first_agent else list(reversed(batch)))
    assert instance.pending['source'] == 'manual'
    assert instance.gate.state == 'ARMED'


def test_stop_wins_agent_batch_and_invalidates_generation(operator):
    instance, _ = operator
    generation = instance.gate.generation
    agent = signed_command(body(instance))
    instance.process_batch(
        [
            ('motion.command', agent),
            ('motion.command', {'action': 'stop', 'source': 'agent'}),
            ('motion.command', command(instance)),
        ]
    )
    assert instance.gate.state == 'DISARMED' and instance.gate.generation != generation
    assert instance.pending is None and instance.last_ack['action'] == 'stop'


@pytest.mark.parametrize(
    'override',
    [{'ts': 998}, {'generation': 'old'}, {'seq': -1}, {'ttl_ms': 501}, {'settings_revision': 999}, {'channel': []}],
)
def test_bad_agent_message_never_disarms_or_stops_manual(operator, override):
    instance, _ = operator
    raw = body(instance, **override)
    try:
        agent = signed_command(raw)
    except ValueError:
        return  # Rejected before it can become a BUS command.
    instance.apply(command(instance))
    before = list(instance.adapter.calls)
    assert instance.apply(agent)['status'] == 'rejected'
    assert instance.gate.state == 'ARMED' and instance.adapter.calls == before


def test_agent_has_no_arm_or_test_permission(operator):
    instance, _ = operator
    agent = signed_command(body(instance))
    for action in ('arm', 'clear_estop', 'height', 'balance', 'action'):
        assert instance.apply({**agent, 'action': action})['status'] == 'rejected'
    instance.apply({'action': 'stop'})
    assert instance.apply(signed_command(body(instance)))['status'] == 'rejected'
    instance.apply(
        command(
            instance,
            'arm',
            execution_context='test',
            operator_consent=True,
            test_operator_consent=True,
            operator_plan='Mock test',
            owner='manual',
            lease_s=5,
        )
    )
    assert instance.apply(signed_command(body(instance)))['reason'] == 'agent_operator_arm_required'


def test_grace_and_active_manual_are_explicit_and_non_disruptive(operator):
    instance, clock = operator
    instance.apply(command(instance, 'height', height=95))
    assert instance.snapshot()['manual_agent_grace_remaining_s'] == pytest.approx(0.5)
    assert instance.apply(signed_command(body(instance)))['reason'] == 'agent_manual_priority'
    assert instance.gate.state == 'ARMED'
    clock.now += 0.6
    assert instance.apply(signed_command(body(instance)))['status'] == 'accepted'


@pytest.fixture
def http_client(operator, monkeypatch):
    instance, clock = operator
    monkeypatch.setattr(safety_contract, 'read_status', instance.snapshot)
    monkeypatch.setattr(safety_contract.time, 'time', clock)
    published = []

    class Publisher:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def publish(self, _, payload):
            published.append(payload)
            instance.apply(payload)
            instance.tick(0.02)

    monkeypatch.setattr(safety_contract, 'BusPub', Publisher)
    monkeypatch.setattr(agent_control_api, 'read_status', instance.snapshot)
    app = Flask(__name__)
    http_contract.install(app, after_request=True)
    agent_control_api.register(app)
    app.add_url_rule('/api/control', 'control', control_api.api_control, methods=['POST'])
    app.add_url_rule('/api/stop', 'stop', control_api.api_stop, methods=['POST'])
    app.add_url_rule('/api/safety', 'safety', control_api.api_safety, methods=['GET', 'POST'])
    return app.test_client(), instance, published


def test_private_api_auth_fixed_source_and_negotiated_contract(http_client):
    client, instance, published = http_client
    headers = {'Authorization': 'Bearer unit-only-agent-token', 'Accept': 'application/vnd.rider.api+json;version=1'}
    denied = client.post('/api/control/agent/pulse', json=body(instance))
    assert denied.status_code == 401 and not published
    result = client.post('/api/control/agent/pulse', json=body(instance), headers=headers)
    assert result.status_code == 200
    assert result.json['meta']['contract_id'] == 'rider.safety'
    assert published[-1]['source'] == published[-1]['execution_context'] == 'agent'
    assert 'unit-only-agent-token' not in json.dumps(result.json)
    assert 'agent_signature' not in json.dumps(result.json)
    verify_command(published[-1])


def test_public_api_cannot_claim_agent_even_with_valid_signature(http_client):
    client, instance, published = http_client
    result = client.post('/api/control', json=signed_command(body(instance)))
    assert result.status_code == 400 and not published
    assert result.json['error'] == 'agent_private_endpoint_required'


def test_private_api_rejects_extra_consent_flags_and_actor_override(http_client):
    client, instance, published = http_client
    for extra in ({'authorized': True}, {'operator_consent': True}, {'source': 'manual'}, {'mode': 'hold'}):
        result = client.post(
            '/api/control/agent/pulse',
            json={**body(instance), **extra},
            headers={'Authorization': 'Bearer unit-only-agent-token'},
        )
        assert result.status_code == 400 and not published


def test_agent_state_and_stop_use_existing_safety_contract(http_client):
    client, instance, published = http_client
    accept = {'Accept': 'application/vnd.rider.api+json;version=1'}
    state = client.get('/api/control/agent/state', headers=accept)
    assert state.json['data']['safety']['agent_epoch'] == instance.gate.agent_epoch
    stop = client.post('/api/stop', json={'source': 'agent', 'execution_context': 'agent'}, headers=accept)
    assert stop.status_code == 200 and stop.json['meta']['contract_id'] == 'rider.safety'
    assert published[-1]['source'] == 'agent' and instance.gate.state == 'DISARMED'


@pytest.mark.parametrize('action', ['stop', 'disarm'])
@pytest.mark.parametrize('armed', [False, True])
@pytest.mark.parametrize('configured', [False, True])
def test_agent_public_safety_stop_works_without_actuator_authorization(
    http_client, monkeypatch, action, armed, configured
):
    client, instance, published = http_client
    if not configured:
        monkeypatch.delenv('RIDER_AGENT_TOKEN')
    if not armed:
        instance.apply({'action': 'disarm'})
    before = len(instance.adapter.calls)
    result = client.post(
        '/api/safety',
        json={'action': action, 'source': 'agent', 'execution_context': 'agent'},
        headers={'Accept': 'application/vnd.rider.api+json;version=1'},
    )
    assert result.status_code == 200 and result.json['ok']
    assert result.json['operation']['confirmed'] is True
    assert result.json['operation']['actuation'] is False
    assert instance.gate.state == 'DISARMED'
    assert published[-1]['source'] == published[-1]['execution_context'] == 'agent'
    assert published[-1]['action'] == action
    assert all(call[0] == 'stop' for call in instance.adapter.calls[before:])


@pytest.mark.parametrize('action', ['move', 'arm', 'height', 'balance'])
def test_public_safety_exception_does_not_allow_agent_actuators(http_client, action):
    client, instance, published = http_client
    before = list(instance.adapter.calls)
    result = client.post(
        '/api/control',
        json=command(instance, action, source='agent', execution_context='agent', height=95, enabled=True),
    )
    assert result.status_code == 400 and result.json['error'] == 'agent_private_endpoint_required'
    assert not published and instance.adapter.calls == before
    assert instance.gate.state == 'ARMED'
