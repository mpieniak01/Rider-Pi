"""API device/resource characterization uses fake reports and recorded subprocesses."""

import copy
import json
import sys
from collections import deque
from types import SimpleNamespace

import pytest
from flask import Flask, jsonify
from test_lcd_observation_contract import clock as lcd_clock, renderer

from services.api_core import (
    compat,
    compat_health,
    contract_registry,
    devices,
    resource_api,
    resource_diag,
    services_api,
)


@pytest.mark.parametrize(
    'raw,expected',
    [('12', 12), ('2.5', 2.5), ('false', False), ('1, 2.5, x', [1, 2.5, 'x']), ('', None), ('plain', 'plain')],
)
def test_legacy_payload_parser_preserves_json_scalar_and_csv(raw, expected):
    assert devices._json_or_raw(raw) == expected


@pytest.mark.parametrize(
    'edits', [{'source': ''}, {'observed_at': 90}, {'observed_at': 101}, {'simulated': True}, {'offline': True}]
)
def test_lcd_invalid_evidence_never_mutates_cache(lcd_clock, edits):
    original = copy.deepcopy(compat.LAST_CAMERA)
    report = renderer()
    report.update(edits)
    devices.observe_lcd(report)
    assert compat.LAST_CAMERA == original


def test_lcd_frame_acceptance_keeps_power_unknown_and_original_nested_times(lcd_clock):
    report = renderer()
    report['lcd']['confirmation'] = 'frame_write_accepted'
    devices.observe_lcd(report)
    cached = compat.LAST_CAMERA['lcd']
    assert cached['on'] is None
    assert cached['power_known'] is False
    assert cached['frame']['observed_at'] == 100
    assert cached['battery']['observed_at'] == 99
    assert cached['frame_source'] == 'lcd-renderer'
    assert cached['rot'] == 270
    result = compat_health.lcd_snapshot(compat, now=100)
    assert result['on'] is None
    assert result['frame'] == report['lcd']['frame']


def test_bus_lcd_dispatch_precedes_generic_observation_and_records_source(monkeypatch):
    events, calls = deque(), []
    monkeypatch.setattr(compat, 'EVENTS', events)
    monkeypatch.setattr(devices, 'observe_lcd', lambda data: calls.append(data))
    monkeypatch.setattr(devices, 'observe_xgo', lambda *_: pytest.fail('LCD reached actuator telemetry'))
    devices._observe_bus_message(devices.LCD_STATE_TOPIC, '{"lcd": {"on": false}}')
    assert calls == [{'lcd': {'on': False}}]
    assert len(events) == 1
    assert events[0]['topic'] == devices.LCD_STATE_TOPIC


def test_bus_loop_dispatches_only_recorded_fake_socket(monkeypatch):
    class EndLoop(BaseException):
        pass

    frames = iter([[b'ui.lcd.state', b'{"lcd": {}}']])
    calls = []

    def receive(**kwargs):
        try:
            return next(frames)
        except StopIteration:
            raise EndLoop() from None

    sub = SimpleNamespace(
        connect=lambda address: calls.append(('connect', address)),
        setsockopt_string=lambda *args: calls.append(('subscribe', args)),
        setsockopt=lambda *_: None,
        recv_multipart=receive,
    )
    fake = SimpleNamespace(
        SUB=1,
        SUBSCRIBE=2,
        RCVTIMEO=3,
        Again=TimeoutError,
        Context=SimpleNamespace(instance=lambda: SimpleNamespace(socket=lambda _: sub)),
    )
    monkeypatch.setitem(sys.modules, 'zmq', fake)
    monkeypatch.setattr(devices, '_observe_bus_message', lambda *args: calls.append(('message', args)))
    with pytest.raises(EndLoop):
        devices.bus_sub_loop()
    assert calls[-1] == ('message', ('ui.lcd.state', '{"lcd": {}}'))
    assert calls[0][0] == 'connect'


@pytest.mark.parametrize(
    'output,error',
    [
        ('p1\0n/dev/video0\0', 'invalid owner PID'),
        ('pabc\0n/dev/video0\0', 'malformed owner PID'),
        ('p42\0cowner\0', 'incomplete'),
        ('p42\0n \0', 'empty owner path'),
    ],
)
def test_lsof_parser_rejects_ambiguous_ownership(output, error):
    with pytest.raises(RuntimeError, match=error):
        resource_diag._parse_lsof(output)


def test_lsof_recorded_command_and_owner_field_order(monkeypatch):
    commands = []
    monkeypatch.setattr(resource_diag.os, 'geteuid', lambda: 0)

    def run(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(returncode=0, stderr='', stdout='p42\0cfixture\0Lpi\0n/dev/video0\0p43\0n/dev/video1\0')

    monkeypatch.setattr(resource_diag.subprocess, 'run', run)
    rows = resource_diag._run_lsof(['/dev/video0', '/dev/video1'])
    assert commands[0][0] == ['lsof', '-FpcuLn0', '--', '/dev/video0', '/dev/video1']
    assert commands[0][1]['timeout'] == 5
    assert [row.pid for row in rows] == [42, 43]
    assert rows[0].paths == ['/dev/video0']
    assert rows[0].command == 'fixture'
    assert rows[0].user == 'pi'


def test_release_journal_failure_precedes_recovery_confirmation_and_signals(tmp_path, monkeypatch):
    path = tmp_path / 'state.json'
    path.write_text('{invalid')
    manager = SimpleNamespace(_state_path=path, resource_consumers=lambda: {})
    monkeypatch.setattr(resource_diag, 'inspect', lambda _: {'holders': [], 'state': 'free'})
    monkeypatch.setattr(resource_diag, '_call_release', lambda *_: pytest.fail('unknown task ownership signalled'))
    result = resource_diag._release_locked('mic', [], False, False, manager, set())
    assert result['error'] == 'task_ownership_unknown'


def test_release_protected_resource_precedes_pid_and_consent_validation(tmp_path, monkeypatch):
    manager = SimpleNamespace(_state_path=tmp_path / 'missing.json', resource_consumers=lambda: {})
    monkeypatch.setattr(resource_diag, 'inspect', lambda _: {'holders': [], 'state': 'free'})
    monkeypatch.setattr(resource_diag, '_call_release', lambda *_: pytest.fail('protected resource signalled'))
    result = resource_diag._release_locked('uart', [], False, False, manager, set())
    assert result['error'] == 'protected_resource'


@pytest.mark.parametrize(
    'payload,error',
    [
        ({'action': 'release', 'pids': True}, 'pids must be a list'),
        ({'action': 'release', 'pids': [True]}, 'invalid pid'),
        ({'action': 'stop', 'units': ['']}, 'units must be a list of names'),
    ],
)
def test_resource_route_rejection_precedes_backend_mutation(monkeypatch, payload, error):
    monkeypatch.setattr(services_api, 'resource_release', lambda *_: pytest.fail('invalid release reached backend'))
    monkeypatch.setattr(services_api, 'resource_stop', lambda *_: pytest.fail('invalid stop reached backend'))
    app = Flask(__name__)
    app.add_url_rule('/resource/<name>', view_func=resource_api.api_resource, methods=['POST'])
    response = app.test_client().post('/resource/mic', json=payload)
    assert response.status_code == 400
    assert response.json['error'] == error


def test_resource_stops_halt_on_first_failure_before_next_owner(monkeypatch):
    calls = []
    monkeypatch.setattr(
        services_api,
        '_manager',
        lambda: SimpleNamespace(service_action=lambda unit, action: calls.append((unit, action)) or {'ok': False}),
    )
    assert services_api._stop_resource_services(['first.service', 'second.service']) == [{'ok': False}]
    assert calls == [('first.service', 'stop')]


def test_task_contract_projection_preserves_input_and_all_nested_task_locations():
    task = {
        'host': 'pi',
        'name': 'mock-task',
        'services': [{'unit': 'rider-api.service', 'active': 'active', 'load': 'loaded'}],
    }
    payload = {
        'ok': True,
        'features': [task],
        'summary': {'features': [task]},
        'state': {'features': [task]},
        'result': {'task': task},
    }
    before = copy.deepcopy(payload)
    result = contract_registry.projection('/api/logic/features', payload)
    assert payload == before
    assert 'ok' not in result
    assert result['features'][0]['identity'] == 'pi:mock-task'
    assert result['summary']['features'][0]['identity'] == 'pi:mock-task'
    assert result['state']['features'][0]['identity'] == 'pi:mock-task'
    assert result['result']['task']['identity'] == 'pi:mock-task'
    assert result['features'][0]['services'][0]['active_state'] == 'active'


def test_event_generator_preserves_cursor_and_original_event_values():
    class Finish(BaseException):
        pass

    sleeps = []

    def sleep(delay):
        sleeps.append(delay)
        if len(sleeps) == 2:
            raise Finish()

    event = {'ts': 10, 'topic': 'fixture', 'data': 'original'}
    context = SimpleNamespace(time=SimpleNamespace(sleep=sleep), EVENTS=[event], json=json)
    from services.api_core.event_stream import EventCursor

    rows = compat_health._event_rows(context, EventCursor)
    assert next(rows) == 'data: ' + json.dumps(event) + '\n\n'
    with pytest.raises(Finish):
        next(rows)
    assert event['ts'] == 10
