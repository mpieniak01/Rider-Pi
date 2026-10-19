"""P4 HTTP contracts with inert source functions and memory-only dependencies."""

import ast
import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, Response, jsonify, make_response, request

ROOT = Path(__file__).resolve().parents[1]


def definitions(relative, names, **scope):
    """Skip module startup and route decorators; retain real function source positions."""
    path = ROOT / relative
    tree = ast.parse(path.read_text())
    selected = [copy.deepcopy(n) for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in selected} == set(names)
    for function in selected:
        function.decorator_list = []
    future = ast.parse('from __future__ import annotations\n').body[0]
    scope.update(Response=Response, jsonify=jsonify, make_response=make_response, request=request)
    exec(compile(ast.Module(body=[future, *selected], type_ignores=[]), str(path), 'exec'), scope)
    return scope


@pytest.mark.parametrize('module,function', [('agent_control_api', 'pulse'), ('playback_api', 'cancel')])
@pytest.mark.parametrize(
    'error,status', [('agent_control_unconfigured', 503), ('agent_auth_required', 401), ('invalid_fields', 400)]
)
def test_authentication_rejection_status_precedes_payload_and_dispatch(module, function, error, status):
    calls = []

    def authenticate(token):
        calls.append(token)
        raise ValueError(error)

    scope = definitions(
        'services/api_core/' + module + '.py',
        {function},
        authenticate=authenticate,
        submit_control=lambda *args, **kwargs: pytest.fail('rejected authentication dispatched control'),
        signed_command=lambda body: pytest.fail('rejected authentication parsed the payload'),
    )
    app = Flask(__name__)
    with app.test_request_context(
        '/fake', method='POST', json={'untrusted': True}, headers={'Authorization': 'invalid'}
    ):
        response = app.make_response(scope[function]())
    assert response.status_code == status
    assert response.mimetype == 'application/json'
    assert response.get_json() == {'ok': False, 'error': error}
    assert calls == ['invalid']


@pytest.mark.parametrize(
    'kind,status,error',
    [
        ('success', 200, None),
        ('busy', 429, 'preview_busy'),
        ('size', 413, 'gesture_too_large'),
        ('invalid', 400, 'invalid_frame'),
    ],
)
def test_face_preview_response_normalization_preserves_http_headers_and_body(kind, status, error):
    calls = []

    def validate(body):
        calls.append('validate')
        if kind == 'invalid':
            raise ValueError('bad gesture')

    scope = definitions(
        'services/api_core/face_studio.py',
        {'frame'},
        validate=validate,
        _preview=lambda body: calls.append('preview') or (None if kind == 'busy' else b'PNG-fake'),
    )
    app = Flask(__name__)
    body = b'x' * 65537 if kind == 'size' else b'{}'
    with app.test_request_context('/frame', method='POST', data=body, content_type='application/json'):
        response = scope['frame']()
    assert isinstance(response, Response)
    assert response.status_code == status
    if kind == 'success':
        assert response.mimetype == 'image/png'
        assert response.data == b'PNG-fake'
        assert response.headers['Cache-Control'] == 'no-store'
    else:
        assert response.mimetype == 'application/json'
        assert response.get_json()['error'] == error
    assert response.headers.get('Retry-After') == ('1' if kind == 'busy' else None)
    assert calls == ([] if kind == 'size' else ['validate'] if kind == 'invalid' else ['validate', 'preview'])


@pytest.mark.parametrize(
    'result,status',
    [
        ({'ok': True, 'error': 'resource_conflict'}, 200),
        ({'ok': False, 'error': 'resource_conflict'}, 409),
        ({'ok': False, 'error': 'backend_unavailable'}, 503),
    ],
)
def test_feature_response_status_keeps_success_before_conflict(result, status):
    calls = []
    manager = SimpleNamespace(set_feature=lambda *args, **kwargs: calls.append((args, kwargs)) or result)
    scope = definitions(
        'services/api_core/features_api.py',
        {'feature_handler'},
        feature_manager=manager,
        _corsify=lambda response: response,
    )
    app = Flask(__name__)
    body = {'enabled': False, 'options': {'reason': 'fake'}}
    with app.test_request_context('/feature', method='POST', json=body):
        response = app.make_response(scope['feature_handler']('fake_feature'))
    assert response.status_code == status
    assert response.get_json()['result'] == result
    assert calls == [(('fake_feature', False), {'options': body['options'], 'control': body})]


@pytest.mark.parametrize(
    'code,operation_id,status,confirmed',
    [(200, 'r1', 'executed', True), (202, 'other', 'unknown', False), (409, 'r1', 'rejected', False)],
)
def test_camera_transaction_ack_never_claims_frame_or_actuation_readiness(code, operation_id, status, confirmed):
    events = []
    scope = definitions('services/api_core/camera_pipeline_api.py', {'_acknowledge_pipeline_operation'})
    app = Flask(__name__)
    with app.test_request_context('/pipeline', method='POST', json={'action': 'start', 'request_id': 'r1'}):
        scope['_acknowledge_pipeline_operation']({'ok': True, 'operation_id': operation_id}, code, events.append)
    assert len(events) == 1
    assert events[0]['status'] == status
    assert events[0]['confirmed'] is confirmed
    assert events[0]['ack_kind'] == ('camera_goal_accepted' if confirmed else None)
    assert events[0]['actuation'] is False
    assert events[0]['physical_completion'] == 'not_applicable'


@pytest.mark.parametrize(
    'result,status', [({'ok': True, 'pending': True}, 200), ({'ok': False, 'pending': True}, 202), ({'ok': False}, 503)]
)
def test_navigator_stop_publishes_stop_after_scoped_request_with_original_status(result, status):
    calls = []
    scope = definitions(
        'services/api_core/navigator_api.py',
        {'api_navigator_stop'},
        request_stop=lambda **kwargs: calls.append(('request', kwargs)) or result,
        C=SimpleNamespace(bus_pub=lambda *args: calls.append(('publish', args))),
        TOPIC_NAVIGATOR_CONTROL='navigator.control',
        time=SimpleNamespace(time=lambda: 100),
        _response=lambda payload, code: (payload, code),
    )
    app = Flask(__name__)
    with app.test_request_context('/stop', method='POST'):
        response = scope['api_navigator_stop']()
    assert response == (result, status)
    assert calls == [
        ('request', {'owner': 'navigation'}),
        ('publish', ('navigator.control', {'action': 'stop', 'ts': 100})),
    ]


@pytest.mark.parametrize(
    'result,status',
    [
        ({'ok': True, 'error': 'unit_not_in_catalog'}, 200),
        ({'ok': False, 'error': 'unit_not_in_catalog'}, 404),
        ({'ok': False, 'error': 'unavailable'}, 503),
    ],
)
def test_service_log_status_keeps_nocache_and_success_precedence(result, status):
    scope = definitions('services/api_core/service_logs.py', {'service_logs'}, read_logs=lambda unit: result)
    app = Flask(__name__)
    with app.app_context():
        response = app.make_response(scope['service_logs']('fake.service'))
    assert response.status_code == status
    assert response.get_json() == result
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize(
    'flags,status',
    [
        ({'released': True, 'pending': True, 'signal_sent': True}, 200),
        ({'pending': True, 'signal_sent': True}, 202),
        ({'signal_sent': True}, 503),
        ({}, 409),
    ],
)
def test_resource_release_response_keeps_confirmation_and_invalidation_order(monkeypatch, flags, status):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        'services.core.resource_observation',
        SimpleNamespace(invalidate=lambda name: calls.append(('invalidate', name))),
    )
    diag = SimpleNamespace(
        available_resources=lambda: ['camera'],
        release=lambda name, **kwargs: calls.append(('release', name, kwargs)) or flags,
    )
    scope = definitions(
        'services/api_core/services_api.py',
        {'resource_release'},
        _known_resource=lambda name: True,
        resource_diag=diag,
        _json=lambda payload, code: (payload, code),
    )
    app = Flask(__name__)
    with app.test_request_context('/release', method='POST', json={'force': True, 'operator_consent': True}):
        response = scope['resource_release']('camera', [123])
    assert response == (flags, status)
    assert calls == [
        ('release', 'camera', {'limit_pids': [123], 'force': True, 'operator_consent': True}),
        ('invalidate', 'camera'),
    ]


@pytest.mark.parametrize('milliseconds,error', [(None, 'frame_unavailable'), (3000, None), (3001, 'frame_stale')])
def test_ram_frame_age_and_error_do_not_become_file_observations(monkeypatch, milliseconds, error):
    metadata = None if milliseconds is None else {'frame_age_ms': milliseconds, 'frame_id': 'camera-1'}
    monkeypatch.setitem(
        sys.modules,
        'apps.camera.pipeline_ipc',
        SimpleNamespace(read_frame=lambda **kwargs: None if metadata is None else (None, metadata)),
    )
    scope = definitions(
        'services/api_core/frames.py',
        {'_ram_description'},
        STREAMS={'raw': ('RAW_PATH', 'raw', '/camera/raw')},
        MAX_AGE_S=3,
    )
    result = scope['_ram_description']('raw', Path('/fake/raw.jpg'), 1000)
    assert result['error'] == error
    assert result['stale'] is (milliseconds is None or milliseconds > 3000)
    assert result['file_observed_at'] is None
    assert result['observed_at'] == (None if milliseconds is None else 1000 - milliseconds / 1000)


def test_frame_path_precedence_does_not_probe_disk_for_explicit_or_ram_path():
    calls = []
    scope = definitions(
        'services/api_core/frames.py',
        {'_selected_path'},
        Path=Path,
        C=SimpleNamespace(SNAP_DIR='/fake'),
        STREAMS={'raw': ('RAW_PATH', 'raw', '/camera/raw')},
        resolve=lambda stream: calls.append(stream) or Path('/disk/raw.jpg'),
    )
    assert scope['_selected_path']('raw', '/explicit.jpg', True) == Path('/explicit.jpg')
    assert scope['_selected_path']('raw', None, True) == Path('/fake/raw.jpg')
    assert calls == []
    assert scope['_selected_path']('raw', None, False) == Path('/disk/raw.jpg')
    assert calls == ['raw']


def test_systemctl_parser_preserves_duplicate_keys_empty_keys_and_embedded_equals():
    scope = definitions('services/api_core/services_dashboard_api.py', {'_parse_systemctl'})
    result = scope['_parse_systemctl']('ActiveState=failed\nnoise\nActiveState=active\n=value\nkey=one=two\nempty=\n')
    assert result == {'ActiveState': 'active', '': 'value', 'key': 'one=two', 'empty': ''}
