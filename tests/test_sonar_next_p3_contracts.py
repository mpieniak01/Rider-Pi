"""P3 characterizations use in-memory images and inert source functions only."""

import ast
import builtins
import copy
import inspect
import math
from pathlib import Path
from types import SimpleNamespace
from typing import get_args, get_type_hints

import numpy as np
import pytest

from apps.ui.face.animator import Animator

ROOT = Path(__file__).resolve().parents[1]


def definitions(relative, names, **scope):
    path = ROOT / relative
    tree = ast.parse(path.read_text())
    functions = [copy.deepcopy(n) for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in functions} == set(names)
    for function in functions:
        function.decorator_list = []
    future = ast.parse('from __future__ import annotations\n').body[0]
    exec(compile(ast.Module(body=[future, *functions], type_ignores=[]), str(path), 'exec'), scope)
    return scope


def imported_by(importer):
    def import_allowed(name, *args, **kwargs):
        if name == '__future__':
            return builtins.__import__(name, *args, **kwargs)
        return importer(name, *args, **kwargs)

    return {**vars(builtins), '__import__': import_allowed}


@pytest.mark.parametrize('width', [10, 25, 100])
def test_tflite_vector_skip_removal_preserves_secondary_classes_scores_and_count(width):
    boxes = np.zeros((1, width, 4), dtype=np.float32)
    classes = np.zeros((1, width), dtype=np.int32)
    scores = np.full((1, width), 0.8, dtype=np.float32)
    weaker = np.full((1, width), 0.2, dtype=np.float32)
    count = np.array([[width]], dtype=np.int32)
    scope = definitions(
        'apps/camera/tflite_detector.py', {'_detection_outputs', '_class_score_outputs', '_preferred_scores'}, np=np
    )
    actual = scope['_detection_outputs']([np.zeros(3), boxes, classes, weaker, scores, count])
    assert actual[0] is boxes
    assert actual[1] is classes
    assert actual[2] is scores
    assert actual[3] is count
    incomplete = scope['_detection_outputs']([np.zeros(3), count])
    assert incomplete[0] is None
    assert incomplete[1] is None
    assert incomplete[2] is None
    assert incomplete[3] is count


@pytest.mark.parametrize(
    'primary_error,expected', [(None, 'primary'), (ImportError, 'fallback'), (RuntimeError, 'fallback')]
)
def test_tflite_interpreter_import_failure_preserves_existing_fallback_class(primary_error, expected):
    calls = []

    class Interpreter:
        def __init__(self, **kwargs):
            calls.append(('construct', kwargs))

        def allocate_tensors(self):
            calls.append('allocate')

        def get_input_details(self):
            return [{'shape': [1, 120, 160, 3]}]

        def get_output_details(self):
            return [{'index': 1}]

    def importer(name, *args, **kwargs):
        if name == 'tflite_runtime.interpreter':
            calls.append('primary')
            if primary_error is not None:
                raise primary_error('fake import failure')
        elif name == 'tensorflow.lite.python.interpreter':
            calls.append('fallback')
        else:
            raise AssertionError('unexpected import: ' + name)
        return SimpleNamespace(Interpreter=Interpreter)

    scope = definitions(
        'apps/camera/tflite_detector.py',
        {'__init__'},
        os=SimpleNamespace(getenv=lambda name, default: default),
        __builtins__=imported_by(importer),
    )
    detector = SimpleNamespace()
    scope['__init__'](detector, '/fake/model.tflite')
    expected_imports = ['primary'] if expected == 'primary' else ['primary', 'fallback']
    assert calls[:-2] == expected_imports
    assert calls[-2:] == [('construct', {'model_path': '/fake/model.tflite', 'num_threads': 2}), 'allocate']
    assert detector.in_w == 160
    assert detector.in_h == 120


def test_tflite_constructor_error_does_not_silently_try_a_second_interpreter():
    calls = []

    def failed_interpreter(**kwargs):
        raise ValueError('fake invalid model')

    def importer(name, *args, **kwargs):
        calls.append(name)
        return SimpleNamespace(Interpreter=failed_interpreter)

    scope = definitions(
        'apps/camera/tflite_detector.py',
        {'__init__'},
        os=SimpleNamespace(getenv=lambda name, default: default),
        __builtins__=imported_by(importer),
    )
    detector = SimpleNamespace()
    with pytest.raises(ValueError, match='fake invalid model'):
        scope['__init__'](detector, '/fake/model.tflite')
    assert calls == ['tflite_runtime.interpreter']


@pytest.mark.parametrize('mode', ['primary', 'fallback', 'missing', 'constructor', 'disabled'])
def test_lcd_factory_local_name_keeps_optional_import_and_failure_behavior(mode):
    calls = []

    def create():
        calls.append('construct')
        if mode == 'constructor':
            raise RuntimeError('fake LCD unavailable')
        return SimpleNamespace(rotation=None)

    def importer(name, globals=None, locals=None, fromlist=(), level=0):
        assert name == 'xgoscreen.LCD_2inch'
        calls.append('from' if fromlist else 'module')
        if mode == 'missing' or mode == 'fallback' and fromlist:
            raise ImportError('fake unavailable import')
        module = SimpleNamespace(LCD_2inch=create)
        return module if fromlist else SimpleNamespace(LCD_2inch=module)

    scope = definitions(
        'apps/camera/preview_lcd_hybrid.py',
        {'_lcd_init'},
        DISABLE_LCD=mode == 'disabled',
        __builtins__=imported_by(importer),
    )
    lcd = scope['_lcd_init']()
    if mode in {'missing', 'constructor', 'disabled'}:
        assert lcd is None
    else:
        assert lcd.rotation == 0
    assert (
        calls
        == {
            'primary': ['from', 'construct'],
            'fallback': ['from', 'module', 'construct'],
            'missing': ['from', 'module'],
            'constructor': ['from', 'construct'],
            'disabled': [],
        }[mode]
    )


@pytest.mark.parametrize('module', ['apps/vision/dispatcher.py', 'apps/vision/detector_tflite.py'])
@pytest.mark.parametrize(
    'topic,kind,default_mode',
    [('vision.face.person', 'face', 'haar'), ('vision.person', 'person', 'ssd'), ('vision.unknown', 'det', 'det')],
)
def test_topic_kind_priority_and_explicit_mode_are_preserved(module, topic, kind, default_mode):
    names = {'normalize_event'}
    if module.endswith('dispatcher.py'):
        names.add('_as_float')
    scope = definitions(module, names)
    payload = {'confidence': 0.7, 'bbox': [1, 2, 3, 4]}
    before = copy.deepcopy(payload)
    actual = scope['normalize_event'](topic, payload)
    assert actual['kind'] == kind
    assert actual['score'] == 0.7
    assert actual['present'] is True
    assert actual['bbox'] == [1, 2, 3, 4]
    assert payload == before
    if module.endswith('dispatcher.py'):
        assert actual['mode'] == default_mode
        assert scope['normalize_event'](topic, {**payload, 'mode': 'hybrid'})['mode'] == 'hybrid'


def test_detection_list_keeps_person_before_face_and_empty_list_remains_negative():
    scope = definitions(
        'apps/vision/dispatcher.py',
        {'normalize_event', '_normalize_detection_list', '_best_detection', '_as_float'},
        MIN_SCORE=0.5,
    )
    payload = {'items': [{'label': 'face-person', 'score': 0.6}, {'label': 'unknown', 'score': 0.99}]}
    actual = scope['normalize_event']('vision.detections', payload)
    assert actual['kind'] == 'person'
    assert actual['score'] == 0.6
    assert actual['present'] is True
    assert actual['mode'] == 'ssd'
    assert scope['normalize_event']('vision.detections', {}) == {
        'kind': 'det',
        'present': False,
        'score': 0.0,
        'bbox': None,
        'mode': 'det',
    }


@pytest.mark.parametrize(
    'value,expected', [(-math.inf, 0.0), (-1, 0.0), (0, 0), (0.5, 0.5), (1, 1), (2, 1.0), (math.inf, 1.0)]
)
def test_clamp_boundaries_keep_original_inclusive_and_nonfinite_behavior(value, expected):
    face = definitions('apps/draw/face_primitives.py', {'_clampf'})
    gestures = definitions('apps/ui/face/gestures.py', {'_clamp01'})
    assert face['_clampf'](value, 0, 1) == expected
    assert gestures['_clamp01'](value) == expected
    assert face['_clampf'](2, 3, 1) == 1
    nan = float('nan')
    assert face['_clampf'](nan, 0, 1) is nan
    assert gestures['_clamp01'](nan) is nan


def test_animation_tick_completes_multiple_channels_without_skipping_live_channel():
    animator = Animator(clock=lambda: 1)

    def channel(end, final):
        return SimpleNamespace(
            started=0, ends=end, initial=0, owner='fake', segments=[{'t0': 0, 't1': end, 'v0': 0, 'v1': final}]
        )

    animator._channels = {'eyes.dx': channel(1, 0.4), 'eyes.dy': channel(0.5, -0.2), 'brows.lift': channel(2, 1)}
    state = animator.tick()
    assert state.eyes.dx == 0.4
    assert state.eyes.dy == -0.2
    assert state.brows.lift == 0.5
    assert animator.owners == {'brows.lift': 'fake'}


def test_robot_factory_annotation_resolves_before_constructing_either_adapter():
    calls = []
    mode = ['0']

    class Physical:
        def __init__(self):
            calls.append('physical')

    class Simulated:
        def __init__(self):
            calls.append('simulated')

    def importer(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 1 and name == 'adapter':
            return SimpleNamespace(XgoAdapter=Physical)
        if level == 1 and name == 'sim':
            return SimpleNamespace(SimulatedXgoAdapter=Simulated)
        if level == 0 and name == 'os':
            return SimpleNamespace(getenv=lambda name, default: mode[0])
        return builtins.__import__(name, globals, locals, fromlist, level)

    path = ROOT / 'drivers/xgo/__init__.py'
    scope = {
        '__name__': 'factory_type_fixture',
        '__package__': 'drivers.xgo',
        '__builtins__': {**vars(builtins), '__import__': importer},
    }
    exec(compile(path.read_text(), str(path), 'exec'), scope)
    factory = scope['get_robot_driver']
    hints = get_type_hints(factory)
    assert set(get_args(hints['return'])) == {Physical, Simulated}
    assert not calls
    assert isinstance(factory(), Physical)
    assert calls == ['physical']
    mode[0] = '1'
    assert isinstance(factory(), Simulated)
    assert calls == ['physical', 'simulated']


def test_adapter_capability_kinds_do_not_probe_unavailable_sdk():
    path = ROOT / 'drivers/xgo/adapter.py'
    tree = ast.parse(path.read_text())
    mapping = next(
        n.value
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'CONTROL_KINDS' for target in n.targets)
    )
    scope = definitions(
        'drivers/xgo/adapter.py',
        {'capabilities'},
        CONTROL_KINDS=ast.literal_eval(mapping),
        posture_parameters=lambda: {},
    )
    owner = SimpleNamespace(ok=lambda: False)
    actual = scope['capabilities'](owner)
    assert {name: row['control_kind'] for name, row in actual.items()} == {
        'move': 'motion',
        'turn': 'motion',
        'balance': 'mode_setting',
        'height': 'position_setpoint',
        'action': 'motion',
    }
    assert all(row['available'] is False for row in actual.values())
    assert all(row['physical_completion'] == 'unverified' for row in actual.values())


def test_legacy_serial_flush_keeps_gap_and_underlying_return_value():
    calls = []
    scope = definitions('drivers/xgo/sniffer.py', {'flushInput'})
    owner = SimpleNamespace(
        _serial=SimpleNamespace(flushInput=lambda: calls.append('flush') or 7),
        _observe=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    assert scope['flushInput'](owner) == 7
    assert calls == ['flush', (('gap',), {'cause': 'flushInput', 'discarded_bytes': 'unknown'})]


def test_deferred_drawing_and_lcd_signatures_remain_callable_without_hardware():
    face = definitions('apps/draw/face_primitives.py', {'draw_face'})
    assert list(inspect.signature(face['draw_face']).parameters) == ['canvas', 'cfg', 'model', 'guide', 'quality']
    assert inspect.signature(face['draw_face']).parameters['quality'].default == 'fast'
    calls = []
    lcd = definitions('drivers/lcd/sim.py', {'ShowImage'})
    frame = object()
    assert lcd['ShowImage'](SimpleNamespace(driver=SimpleNamespace(push_png=calls.append)), frame) is None
    assert calls == [frame]
    tree = ast.parse((ROOT / 'drivers/lcd/ili9xx_device.py').read_text())
    renderer = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'LCDRenderer')
    alias = next(
        n
        for n in renderer.body
        if isinstance(n, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'ShowImage' for target in n.targets)
    )
    assert alias.value.id == 'show_image'


def test_ui_overlay_keeps_safety_output_and_vision_text_in_display_order():
    calls = []
    screen = SimpleNamespace(
        fill=lambda color: calls.append(('fill', color)),
        blit=lambda image, position: calls.append(('blit', image, position)),
    )
    font = SimpleNamespace(render=lambda text, antialias, color: text)
    scope = definitions(
        'apps/ui/overlay.py',
        {'_draw_overlay'},
        display_motion=lambda motion: motion,
        number_label=str,
        pygame=SimpleNamespace(display=SimpleNamespace(flip=lambda: calls.append('flip'))),
    )
    scope['_draw_overlay'](
        screen,
        font,
        {
            'motion': {'state': 'STOP', 'can_move': False, 'output': {'lx': 0, 'az': 0}},
            'vision': {'moving': False, 'human': True, 'motion': 1.25},
        },
    )
    assert calls == [
        ('fill', (0, 0, 0)),
        ('blit', 'SAFETY: STOP can_move=False', (20, 20)),
        ('blit', 'OUT normalized: lx=0 az=0', (20, 48)),
        ('blit', 'Physical motion/stop: unverified', (20, 76)),
        ('blit', 'VISION: moving=False human=True motion=1.2', (20, 104)),
        'flip',
    ]


def test_roi_bins_keep_partial_last_bin_and_empty_slice_behavior():
    scope = definitions(
        'apps/vision/obstacle_roi.py',
        {'bins_edge_pcts'},
        cv2=SimpleNamespace(countNonZero=np.count_nonzero),
    )
    edges = np.array([[1, 0, 1, 1, 0], [0, 0, 1, 1, 1]], dtype=np.uint8)
    assert scope['bins_edge_pcts'](edges, slice(0, 2), 2) == [0.25, 5 / 6]
    assert scope['bins_edge_pcts'](edges, slice(0, 0), 3) == [0, 0, 0]
    assert scope['bins_edge_pcts'](edges, slice(0, 2), 0) == [0.6]


@pytest.mark.parametrize('present,color', [(False, (0, 200, 0)), (True, (0, 0, 220))])
def test_roi_annotation_retains_coordinates_low_bin_and_jpeg_parameters(present, color):
    calls = []
    cv = SimpleNamespace(
        rectangle=lambda *args, **kwargs: calls.append(('rectangle', args[1:], kwargs)),
        addWeighted=lambda *args: calls.append(('blend', args[1], args[3], args[4])),
        line=lambda *args: calls.append(('line', args[1:])),
        putText=lambda *args: calls.append(('text', args[1:])),
        imwrite=lambda *args: calls.append(('write', args[0], args[2])),
        FONT_HERSHEY_SIMPLEX=0,
        LINE_AA=16,
        IMWRITE_JPEG_QUALITY=1,
    )
    image = np.zeros((6, 8, 3), dtype=np.uint8)
    scope = definitions(
        'apps/vision/obstacle_roi.py',
        {'draw_overlay'},
        cv2=cv,
        _to_bgr=lambda original: original.copy(),
        EDGE_BIN_LOW=0.1,
    )
    scope['draw_overlay'](image, slice(2, 5), present, 0.5, 0.25, [0.05, 0.1], '/fake/annotation.jpg')
    assert calls[0] == ('rectangle', ((0, 2), (7, 4), color), {'thickness': -1})
    assert calls[1] == ('blend', 0.15, 0.85, 0)
    assert calls[2:4] == [
        ('line', ((0, 2), (7, 2), (180, 180, 0), 1)),
        ('line', ((0, 5), (7, 5), (180, 180, 0), 1)),
    ]
    assert calls[4] == ('rectangle', ((0, 2), (3, 4), (0, 0, 255), 1), {})
    assert calls[5][1][0] == f'present={present} conf=0.50 edge=0.250'
    assert calls[6] == ('write', '/fake/annotation.jpg', [1, 85])
    assert np.count_nonzero(image) == 0
