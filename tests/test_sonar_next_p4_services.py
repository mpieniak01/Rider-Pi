"""P4 state and callback contracts; only fake clocks, requests and owners are used."""

import ast
import logging
import math
import subprocess
from collections import OrderedDict, deque
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from test_sonar_next_p4_api import ROOT, definitions


@pytest.mark.parametrize(
    'available,installed,permissions,allowed,reason',
    [
        (False, False, [], False, 'domain_unavailable'),
        (True, False, [], False, 'unit_unavailable'),
        (True, True, [None, None], True, None),
        (True, True, ['blocked', 'blocked'], False, 'operator_motion_permission_required'),
        (True, True, [None, 'changed'], True, 'operator_motion_permission_required'),
    ],
)
def test_feature_permission_priority_and_callback_observation_count(available, installed, permissions, allowed, reason):
    calls = []
    values = iter(permissions)

    def permission(feature):
        calls.append(feature)
        return next(values)

    owner = SimpleNamespace(_permission=permission)
    scope = definitions('services/core/feature_state.py', {'_feature_permissions'})
    result = scope['_feature_permissions'](
        owner,
        'fake-feature',
        {'start_available': available, 'start_unavailable_reason': 'domain_unavailable'},
        installed,
    )
    assert result == {'start': {'allowed': allowed, 'reason': reason}, 'stop': {'allowed': True, 'reason': None}}
    assert calls == ['fake-feature'] * len(permissions)


@pytest.mark.parametrize(
    'row,active,state',
    [
        ({'active': 'active'}, True, 'active'),
        ({'active': 'active', 'error': 'failed'}, False, 'failed'),
        ({'active': 'failed'}, False, 'failed'),
        ({'active': 'active', 'stale': True}, False, 'stopped'),
        ({'active': 'inactive'}, False, 'stopped'),
    ],
)
def test_legacy_camera_status_does_not_derive_readiness_from_stale_unit(row, active, state):
    calls = []
    manager = SimpleNamespace(PREVIEW_UNIT='fake-camera.service', _status=lambda unit: calls.append(unit) or row)
    scope = definitions('services/camera_pipeline.py', {'_legacy_status'})
    profile = {'mode': 'raw'}
    result = scope['_legacy_status'](SimpleNamespace(manager=manager), profile)
    assert result == (active, state, {'active_profile': profile if active else None})
    if active:
        assert result[2]['active_profile'] is not profile
    assert calls == ['fake-camera.service']


@pytest.mark.parametrize(
    'paths,holders,error,state,free',
    [
        ([], [], 'denied', 'unknown', None),
        ([], [], None, 'unavailable', None),
        (['/fake'], [{'pid': 123}], None, 'busy', False),
        (['/fake'], [], None, 'free', True),
    ],
)
def test_resource_observation_state_keeps_error_before_path_and_holder_evidence(paths, holders, error, state, free):
    calls = []

    def lsof(selected):
        calls.append(selected)
        if error:
            raise OSError(error)
        return []

    scope = definitions(
        'services/api_core/resource_diag.py',
        {'inspect'},
        RESOURCE_SPECS={'camera': {'paths': ['/fake'], 'matcher': None, 'label': 'Camera'}},
        _existing_paths=lambda spec: paths,
        _run_lsof=lsof,
        _matching_holders=lambda processes, matcher: holders,
        subprocess=subprocess,
        time=SimpleNamespace(time=lambda: 1000),
    )
    result = scope['inspect']('camera')
    assert result['state'] == state
    assert result['free'] is free
    assert result['error'] == error
    assert result['observed_at'] == (None if error else 1000)
    assert calls == [paths]


def test_playback_expiry_removes_every_expired_entry_without_mutating_live_iteration():
    scope = definitions('services/audio_playback.py', {'_remember'})
    recent = OrderedDict([('old1', (99, {})), ('old2', (100, {})), ('live', (101, {'ok': True}))])
    owner = SimpleNamespace(recent=recent, clock=lambda: 100)
    result = {'state': 'played'}
    scope['_remember'](owner, 'new', result)
    assert list(recent) == ['live', 'new']
    assert recent['new'] == (160, result)
    for index in range(70):
        scope['_remember'](owner, str(index), result)
    assert len(recent) == 64
    assert next(iter(recent)) == '6'


def test_domain_recovery_uses_a_stable_outage_snapshot_despite_callback_changes():
    outages, events = {'good', 'bad'}, []

    def state(domain):
        if domain == 'bad':
            raise OSError('observation unavailable')
        outages.discard(domain)
        outages.add('late')
        return {'mode': 'pc'}

    scope = definitions(
        'services/provider_watchdog.py',
        {'_restore_domains'},
        _fallbacked_domains=outages,
        registry=SimpleNamespace(
            get_domain_state=state, update_domain_status=lambda *args, **kwargs: events.append((args, kwargs))
        ),
        LOG=SimpleNamespace(warning=lambda *args: events.append(('warning',))),
    )
    scope['_restore_domains']()
    assert outages == {'bad', 'late'}
    assert (('good', 'pc_pending'), {'reason': 'heartbeat_recover'}) in events
    assert ('warning',) in events
    assert len(events) == 2


@pytest.mark.parametrize(
    'error,playing,status,code',
    [
        (OSError('lcd_lease_failed'), False, 503, 'lcd_unavailable'),
        (RuntimeError('device unavailable'), True, 503, 'lcd_unavailable'),
        (ValueError('lcd_owned'), False, 409, 'lcd_owned'),
        (ValueError('gesture_invalid'), False, 400, 'gesture_invalid'),
    ],
)
def test_face_error_status_preserves_unavailability_priority_and_active_state(error, playing, status, code):
    state = {'playing': playing, 'error': 'prior'}
    scope = definitions('services/api_core/face_anim.py', {'_play_error'}, STATE=state, _STATE_LOCK=nullcontext())
    result = scope['_play_error'](error)
    assert result == {'ok': False, 'error': code, 'detail': str(error), 'status': status}
    assert state['error'] == ('prior' if playing else code)


@pytest.mark.parametrize(
    'result,status',
    [
        ({'ok': True, 'state': 'failed'}, 200),
        ({'ok': False, 'state': 'failed'}, 503),
        ({'ok': False, 'state': 'cancelled'}, 409),
    ],
)
def test_playback_status_keeps_cleanup_after_the_return_decision(result, status):
    events = []

    class Event:
        flag = False

        def set(self):
            self.flag = True

    class Timer:
        def __init__(self, **kwargs):
            events.append('timer-created')

        def start(self):
            events.append('timer-started')

        def is_alive(self):
            return True

        def join(self, timeout):
            events.append(('timer-joined', timeout))

    scope = definitions(
        'services/audio_playback.py',
        {'execute'},
        identifier=lambda value: value,
        validate_wav=lambda data: 16000,
        math=math,
        threading=SimpleNamespace(Event=Event, Thread=Timer),
    )
    done = Event()
    owner = SimpleNamespace(
        _reserve=lambda *args: None,
        _expire=lambda *args: None,
        _result=lambda *args, **kwargs: {'ok': False, 'state': 'failed'},
        _run_playback=lambda *args: result,
        lock=nullcontext(),
        active='fake',
        done=done,
        _remember=lambda key, value: events.append(('remember', key, value)),
    )
    actual = scope['execute'](owner, b'fake wav', 'fake-id', 10)
    assert actual == (result, status)
    assert owner.active is None
    assert done.flag is True
    assert events == ['timer-created', 'timer-started', ('timer-joined', 0.2), ('remember', 'fake-id', result)]


def test_route_aliases_register_from_a_bounded_snapshot_of_a_mutating_map():
    path = ROOT / 'services/api_server.py'
    tree = ast.parse(path.read_text())
    setup = next(
        node
        for node in tree.body
        if isinstance(node, ast.Try)
        and any(
            isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'rules_to_alias' for t in n.targets)
            for n in node.body
        )
    )
    nodes = [
        n
        for n in setup.body
        if isinstance(n, ast.For)
        or isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'rules_to_alias' for t in n.targets)
    ]
    rules = [
        SimpleNamespace(rule='/frame', endpoint='vision.frame', methods={'GET'}, provide_automatic_options=True),
        SimpleNamespace(rule='/health', endpoint='health', methods={'GET'}, provide_automatic_options=True),
    ]
    visited, added = [], []

    def iterate():
        for rule in rules:
            visited.append(rule.endpoint)
            yield rule

    def add(path, **kwargs):
        added.append((path, kwargs))
        rules.append(SimpleNamespace(endpoint=kwargs['endpoint']))

    view = object()
    app = SimpleNamespace(
        url_map=SimpleNamespace(iter_rules=iterate), add_url_rule=add, view_functions={'vision.frame': view}
    )
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), {'app': app, 'prefix': 'vision.'})
    assert visited == ['vision.frame', 'health']
    assert added == [
        (
            '/api/frame',
            {
                'endpoint': 'vision_api_alias.frame',
                'view_func': view,
                'methods': {'GET'},
                'provide_automatic_options': True,
            },
        )
    ]


@pytest.mark.parametrize('method', ['get_devices', 'send_command'])
def test_google_request_error_logging_keeps_traceback_without_real_requests(method, caplog):
    class RequestFailure(Exception):
        pass

    def fail(*args, **kwargs):
        raise RequestFailure('fake request failure')

    logger = logging.getLogger('p4.google.fake')
    scope = definitions(
        'services/api_core/google_home_api.py',
        {method},
        PROJECT_ID='fake-project',
        API_BASE='https://fake.invalid',
        API_TIMEOUT=2,
        refresh_access_token=lambda: 'fake-token',
        requests=SimpleNamespace(get=fail, post=fail, exceptions=SimpleNamespace(RequestException=RequestFailure)),
        logger=logger,
    )
    with caplog.at_level(logging.ERROR, logger=logger.name):
        result = scope[method]() if method == 'get_devices' else scope[method]('fake-device', 'fake.command')
    assert result == {'ok': False, 'error': 'fake request failure'}
    assert len(caplog.records) == 1
    assert caplog.records[0].exc_info[0] is RequestFailure
    assert caplog.records[0].levelno == logging.ERROR


def test_internal_system_history_names_keep_deque_updates_in_place():
    expected = {'hist_cpu': [10, 20], 'hist_mem': [30, 40], 'cpu_pct': 20}
    scope = definitions(
        'services/api_core/system_info.py',
        {'get_sysinfo'},
        _sampler=SimpleNamespace(lock=nullcontext(), snapshot=lambda: dict(expected)),
    )
    cpu, memory = deque([1]), deque([2])
    result = scope['get_sysinfo'](hist_cpu=cpu, hist_mem=memory)
    assert result == expected
    assert list(cpu) == [10, 20]
    assert list(memory) == [30, 40]
