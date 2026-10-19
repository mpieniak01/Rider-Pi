"""Camera/vision boundaries with inert AST functions at their real source positions.

Hardware modules have import-time publishers, LCD initialization or model imports.
Only selected function nodes are compiled; camera, CV and output owners are fakes.
The unchanged AST line numbers and filename also make coverage attributable to source.
"""

import ast
import posixpath
from collections import deque
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
HYBRID = 'apps/camera/preview_lcd_hybrid.py'
SSD = 'apps/camera/ssd_preview_writer.py'
TRACKER = 'apps/vision/tracker_mediapipe.py'
OBSTACLE = 'apps/vision/obstacle_roi.py'


class EndFrames(BaseException):
    """End a bounded fake acquisition without entering production error retries."""


def functions(relative, names, **namespace):
    path = ROOT / relative
    tree = ast.parse(path.read_text(), filename=str(path))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in selected} == set(names)
    future = ast.parse('from __future__ import annotations\n').body[0]
    module = ast.Module(body=[future, *selected], type_ignores=[])
    namespace['__file__'] = str(path)
    exec(compile(module, str(path), 'exec', dont_inherit=True), namespace)
    return namespace


def image():
    return np.zeros((100, 200, 3), dtype=np.uint8)


class CV:
    COLOR_BGR2GRAY = 'gray'
    COLOR_BGR2RGB = 'rgb'
    FONT_HERSHEY_SIMPLEX = 'font'
    LINE_AA = 'aa'

    def __init__(self):
        self.calls = []
        self.dnn = SimpleNamespace(blobFromImage=self.blob)

    def resize(self, frame, size):
        self.calls.append(('resize', size))
        return frame

    def blob(self, frame, *args, **kwargs):
        self.calls.append(('blob', frame.shape, args, kwargs))
        return 'fake-blob'

    def rectangle(self, frame, *args):
        self.calls.append(('rectangle', args))

    def putText(self, frame, text, *args):
        self.calls.append(('text', text))

    def circle(self, frame, *args):
        self.calls.append(('circle', args))

    def cvtColor(self, frame, mode):
        self.calls.append(('color', mode))
        return frame[:, :, 0] if mode == self.COLOR_BGR2GRAY else frame


def network(rows):
    detections = np.array([[rows]], dtype=float)
    calls = []
    return SimpleNamespace(setInput=calls.append, forward=lambda: detections), calls


def hybrid(**overrides):
    messages = []
    defaults = {
        "cv2": CV(),
        "NO_DRAW": False,
        "PERSON_ID": 15,
        "pub": lambda *args, **kwargs: messages.append((args, kwargs)),
    }
    defaults.update(overrides)
    namespace = functions(
        HYBRID,
        {'_update_hybrid_tracker', '_hybrid_best_detection', '_apply_hybrid_detection', '_hybrid_haar_roi'},
        **defaults,
    )
    return namespace, messages


@pytest.mark.parametrize('draw', [True, False])
def test_hybrid_tracker_success_keeps_bbox_and_publishes_with_or_without_overlay(draw):
    tracker = SimpleNamespace(update=lambda frame: (True, (1.9, 2.8, 3.7, 4.6)))
    namespace, messages = hybrid(NO_DRAW=not draw)
    result = namespace['_update_hybrid_tracker'](image(), tracker, None, False)
    assert result == (tracker, (1, 2, 3, 4), True)
    assert messages == [(('vision.person', {'present': True, 'score': 0.75, 'bbox': [1, 2, 3, 4]}), {'add_ts': True})]
    rectangles = [call for call in namespace['cv2'].calls if call[0] == 'rectangle']
    assert len(rectangles) == int(draw)


def test_hybrid_tracker_loss_discards_prior_box_without_false_observation():
    namespace, messages = hybrid()
    tracker = SimpleNamespace(update=lambda frame: (False, (9, 9, 9, 9)))
    assert namespace['_update_hybrid_tracker'](image(), tracker, (1, 2, 3, 4), True) == (None, None, False)
    assert messages == []
    assert namespace['_update_hybrid_tracker'](image(), None, None, False) == (None, None, False)


def test_hybrid_ssd_filters_class_and_threshold_before_selecting_best_person():
    net, inputs = network(
        [
            [0, 15, 0.49, 0, 0, 0.8, 0.8],
            [0, 7, 0.99, 0, 0, 1, 1],
            [0, 15, 0.5, 0.1, 0.2, 0.4, 0.6],
            [0, 15, 0.8, 0.2, 0.1, 0.7, 0.9],
            [0, 15, 0.8, 0.5, 0.5, 1, 1],
        ]
    )
    namespace, messages = hybrid()
    assert namespace['_hybrid_best_detection'](image(), net, 0.5) == (0.8, (40, 10, 140, 90))
    assert inputs == ['fake-blob']
    assert messages == []


@pytest.mark.parametrize('draw', [True, False])
def test_hybrid_new_detection_publishes_before_tracker_initialization(draw):
    events = []
    tracker = SimpleNamespace(init=lambda frame, box: events.append(('init', box)))
    namespace, _ = hybrid(
        NO_DRAW=not draw,
        create_tracker=lambda: events.append(('create',)) or tracker,
        pub=lambda topic, payload, **kw: events.append(('publish', topic, payload)),
    )
    result = namespace['_apply_hybrid_detection'](image(), (0.8, (10, 20, 40, 70)), None, None)
    assert result == (tracker, (10, 20, 30, 50))
    assert [event[0] for event in events] == ['publish', 'create', 'init']
    assert events[-1] == ('init', (10, 20, 30, 50))
    assert namespace['_apply_hybrid_detection'](image(), None, tracker, (1, 2, 3, 4)) == (tracker, (1, 2, 3, 4))


@pytest.mark.parametrize('draw', [True, False])
def test_hybrid_haar_clips_negative_roi_and_never_calls_classifier_on_empty_slice(draw):
    seen = []
    haar = SimpleNamespace(detectMultiScale=lambda gray, **kwargs: seen.append((gray.shape, kwargs)) or [(1, 2, 3, 4)])
    namespace, messages = hybrid(NO_DRAW=not draw)
    namespace['_hybrid_haar_roi'](image(), haar, (-10, -5, 30, 25))
    assert seen[0][0] == (20, 20)
    assert seen[0][1] == {'scaleFactor': 1.1, 'minNeighbors': 4, 'minSize': (20, 20)}
    assert messages[0][0] == ('vision.face', {'present': True, 'score': 0.85, 'count': 1})
    namespace['_hybrid_haar_roi'](image(), haar, (250, 0, 10, 20))
    namespace['_hybrid_haar_roi'](image(), None, (0, 0, 10, 20))
    assert len(seen) == 1
    assert len(messages) == 1


def fake_time():
    state = SimpleNamespace(now=100.0, sleeps=[])

    def tick():
        state.now += 0.1
        return state.now

    return SimpleNamespace(time=tick, sleep=state.sleeps.append), state


def test_hybrid_main_skips_failed_read_and_runs_ssd_only_at_configured_cadence():
    frame = image()
    reads = iter([(False, None), (True, frame), (True, frame), (True, frame)])
    events = []

    def read():
        try:
            return next(reads)
        except StopIteration:
            raise EndFrames() from None

    timer, clock = fake_time()
    environment = {'SSD_EVERY': '2', 'LOG_EVERY': '1', 'HYBRID_HAAR': '0'}
    namespace = functions(
        HYBRID,
        {'main'},
        os=SimpleNamespace(getenv=lambda key, default: environment.get(key, default)),
        time=timer,
        open_camera=lambda size: (read, size),
        load_ssd=lambda: 'net',
        load_haar=lambda: pytest.fail('disabled Haar initialized'),
        ROT=270,
        FLIP_H=False,
        FLIP_V=False,
        NO_DRAW=True,
        apply_rotation=lambda frame, *args: frame,
        _update_hybrid_tracker=lambda *args: (None, None, False),
        _hybrid_best_detection=lambda *args: events.append('ssd') or None,
        _apply_hybrid_detection=lambda *args: (None, None),
        _hybrid_haar_roi=lambda *args: events.append('roi'),
        SNAP=SimpleNamespace(
            **{
                name: (lambda *args, name=name: events.append(name))
                for name in ('cam', 'proc', 'lcd_from_frame', 'lcd_from_fb')
            }
        ),
        lcd_show_bgr=lambda frame: events.append('lcd'),
        HB=SimpleNamespace(tick=lambda *args, **kwargs: events.append(('heartbeat', args, kwargs))),
    )
    with pytest.raises(EndFrames):
        namespace['main']()
    assert events.count('ssd') == 2
    assert events.count('cam') == 3
    assert events.count('lcd') == 3
    assert clock.sleeps == [0.01]
    heartbeats = [event for event in events if isinstance(event, tuple)]
    assert len(heartbeats) == 4
    assert heartbeats[0][1] == (None, 0.0)
    assert all(event[2] == {'presenting': False} for event in heartbeats)


@pytest.mark.parametrize(
    'draw,classes,expected',
    [(True, {'person'}, ['person:0.70']), (False, {'person'}, []), (True, set(), ['person:0.70', '99:0.90'])],
)
def test_ssd_writer_filters_clips_and_rejects_collapsed_boxes(draw, classes, expected):
    net, inputs = network(
        [
            [0, 1, 0.2, 0, 0, 1, 1],
            [0, 1, 0.7, -0.2, -0.1, 1.2, 1.1],
            [0, 1, 0.8, 0.6, 0.1, 0.2, 0.9],
            [0, 99, 0.9, 0.1, 0.2, 0.3, 0.6],
        ]
    )
    cv = CV()
    namespace = functions(SSD, {'_draw_ssd_frame'}, cv2=cv, NO_DRAW=not draw, CLASSES=['background', 'person'])
    frame = image()
    namespace['_draw_ssd_frame'](frame, frame.copy(), net, 0.5, classes)
    assert [call[1] for call in cv.calls if call[0] == 'text'] == expected
    assert inputs == ['fake-blob']
    rectangles = [call for call in cv.calls if call[0] == 'rectangle']
    if draw:
        assert rectangles[0][1][:2] == ((0, 0), (199, 99))
    else:
        assert rectangles == []


@pytest.mark.parametrize('exists,size', [(True, 321), (False, -1)])
def test_ssd_snapshot_diagnostic_respects_cadence_and_missing_file(exists, size, capsys):
    seen = []
    namespace = functions(
        SSD,
        {'_log_writer_snapshot'},
        SNAP_DIR='/fake',
        _PROC_FRAME_NAME='proc.jpg',
        os=SimpleNamespace(
            path=SimpleNamespace(
                join=posixpath.join, exists=lambda path: exists, getsize=lambda path: seen.append(path) or 321
            )
        ),
    )
    namespace['_log_writer_snapshot'](29, True, False)
    assert capsys.readouterr().out == ''
    namespace['_log_writer_snapshot'](30, True, False)
    assert f'size={size}B  ok_raw=True ok_proc=False' in capsys.readouterr().out
    assert seen == (['/fake/proc.jpg'] if exists else [])


def test_ssd_main_keeps_snapshot_and_lcd_delivery_on_non_detection_frames():
    frame = image()
    reads = iter([(False, None), (True, frame), (True, frame), (True, frame)])
    calls = []

    def read():
        try:
            return next(reads)
        except StopIteration:
            raise EndFrames() from None

    namespace = functions(
        SSD,
        {'main'},
        os=SimpleNamespace(
            getenv=lambda key, default: '2' if key == 'SSD_EVERY' else default,
            path=SimpleNamespace(join=posixpath.join),
        ),
        time=SimpleNamespace(sleep=lambda dt: calls.append(('sleep', dt))),
        open_camera=lambda: (read, (200, 100)),
        load_ssd=lambda: 'net',
        SNAP_DIR='/fake',
        ROT=270,
        DISABLE_LCD=True,
        _PROC_FRAME_NAME='proc.jpg',
        apply_rotation=lambda frame: frame,
        _draw_ssd_frame=lambda *args: calls.append(('ssd',)),
        atomic_write=lambda path, *args: calls.append(('write', path)) or not path.endswith('proc.jpg'),
        _log_writer_snapshot=lambda *args: calls.append(('log', args)),
        lcd_show_bgr=lambda frame: calls.append(('lcd',)),
    )
    with pytest.raises(EndFrames):
        namespace['main']()
    assert calls.count(('ssd',)) == 2
    assert calls.count(('write', '/fake/raw.jpg')) == 3
    assert calls.count(('write', '/fake/proc.jpg')) == 3
    assert calls.count(('lcd',)) == 3
    assert ('log', (0, True, False)) in calls
    assert calls[0] == ('sleep', 0.01)


def test_tracking_controls_preserve_mode_on_invalid_input_and_recover_after_receive_error(capsys):
    receives = iter(
        [
            ('', {}),
            ('camera.heartbeat', {'last_frame_path': '/fake/latest.jpg'}),
            ('camera.heartbeat', {'last_frame_path': ''}),
            ('camera.heartbeat', {'last_frame_path': 12}),
            ('unrelated', {'mode': 'hand'}),
            ('tracking.mode:set', {'mode': ' face '}),
            ('tracking.mode', {'mode': 'invalid'}),
            RuntimeError('receive failed'),
            ('tracking.mode', {'mode': 'hand', 'enabled': False}),
            ('tracking.mode', {'mode': 'hand'}),
            KeyboardInterrupt(),
        ]
    )
    sleeps = []
    observed_modes = []

    def receive():
        observed_modes.append(namespace['FOLLOW_MODE'])
        value = next(receives)
        if isinstance(value, BaseException):
            raise value
        return value

    namespace = functions(
        TRACKER,
        {'control_loop', '_apply_tracking_control', '_set_tracking_mode'},
        FOLLOW_MODE='NONE',
        LAST_FRAME_PATH='/fake/old.jpg',
        FOLLOW_MODE_LOCK=nullcontext(),
        sub_recv=receive,
        time=SimpleNamespace(sleep=sleeps.append),
    )
    namespace['control_loop']()
    assert namespace['LAST_FRAME_PATH'] == '/fake/latest.jpg'
    assert namespace['FOLLOW_MODE'] == 'HAND'
    assert observed_modes == ['NONE', 'NONE', 'NONE', 'NONE', 'NONE', 'NONE', 'FACE', 'FACE', 'FACE', 'NONE', 'HAND']
    assert sleeps == [0.1]
    assert 'control_loop err: receive failed' in capsys.readouterr().out


@pytest.mark.parametrize('stream_frame,admitted', [(None, True), (image(), False)])
def test_shared_tracking_rejects_missing_or_unadmitted_frame_without_file_fallback(stream_frame, admitted):
    calls = []
    stream = SimpleNamespace(
        recv=lambda timeout: calls.append(('recv', timeout)) or stream_frame, metadata={'frame_id': 4}
    )
    namespace = functions(
        TRACKER,
        {'_tracking_frame'},
        time=SimpleNamespace(sleep=lambda dt: calls.append(('sleep', dt))),
        cv2=SimpleNamespace(imread=lambda path: pytest.fail('shared rejection fell back to file')),
    )
    guard = SimpleNamespace(admit=lambda metadata: calls.append(('admit', metadata)) or admitted)
    assert namespace['_tracking_frame'](stream, True, guard, 0.1, 10) is None
    assert calls[0] == ('recv', 100)
    assert calls[-1] == ('sleep', 0.02)
    assert len(calls) == (3 if stream_frame is not None else 2)


@pytest.mark.parametrize('kind', ['missing', 'old', 'stat-error'])
def test_tracking_file_fallback_handles_absence_old_capture_and_stat_failure(kind, capsys):
    calls = []
    frame = image()

    def mtime(path):
        calls.append(('stat', path))
        if kind == 'stat-error':
            raise OSError('unavailable metadata')
        return 8.0

    namespace = functions(
        TRACKER,
        {'_tracking_frame'},
        LAST_FRAME_PATH='/fake/latest.jpg',
        cv2=SimpleNamespace(imread=lambda path: calls.append(('read', path)) or (None if kind == 'missing' else frame)),
        os=SimpleNamespace(path=SimpleNamespace(getmtime=mtime)),
        time=SimpleNamespace(sleep=lambda dt: calls.append(('sleep', dt))),
    )
    result = namespace['_tracking_frame'](None, False, None, 0.1, 10.0)
    if kind == 'missing':
        assert result is None
        assert calls == [('read', '/fake/latest.jpg'), ('sleep', 0.05)]
        assert 'cannot read frame' in capsys.readouterr().out
    else:
        assert result[0] is frame
        assert result[1] == {}
        output = capsys.readouterr().out
        assert ('last_frame age=2.00s' in output) == (kind == 'old')


@pytest.mark.parametrize('mode,pc,has_detection', [('HAND', False, False), ('HAND', True, True), ('FACE', True, False)])
def test_tracking_detection_respects_face_pc_gate_and_hand_empty_result(mode, pc, has_detection):
    calls = []
    landmarks = [SimpleNamespace(landmark=[SimpleNamespace(x=0.75, y=0.2)])]
    hand = SimpleNamespace(
        process=lambda frame: calls.append('hand')
        or SimpleNamespace(multi_hand_landmarks=landmarks if has_detection else [])
    )
    namespace = functions(
        TRACKER,
        {'_detect_tracking', 'calculate_offset_x'},
        cv2=CV(),
        DEAD_ZONE=0.1,
    )
    face = SimpleNamespace(process=lambda frame: pytest.fail('PC face detection bypassed provider gate'))
    offset, detections = namespace['_detect_tracking'](image(), mode, pc, face, hand)
    assert calls == (['hand'] if mode == 'HAND' else [])
    assert offset == (0.5 if has_detection else None)
    assert detections == (landmarks if has_detection else None)


@pytest.mark.parametrize(
    'pc,mode,overlay', [(True, 'HAND', 'remote'), (False, 'NONE', 'idle'), (False, 'HAND', 'Mode Hand')]
)
def test_tracking_annotation_uses_copy_and_hand_marker_without_mutating_capture(pc, mode, overlay):
    cv = CV()
    saved = []
    frame = image()
    detections = [SimpleNamespace(landmark=[SimpleNamespace(x=0.75, y=0.2)])]
    namespace = functions(
        TRACKER,
        {'_save_annotated_tracking', '_draw_tracking_marker'},
        cv2=cv,
        PC_OVERLAY='remote',
        IDLE_OVERLAY='idle',
        MODE_OVERLAY='Mode {mode}',
        save_tracker_frame=saved.append,
    )
    namespace['_save_annotated_tracking'](frame, detections, 12.34, mode, pc)
    assert [call[1] for call in cv.calls if call[0] == 'text'] == ['FPS: 12.3', overlay]
    assert [call[1][:2] for call in cv.calls if call[0] == 'circle'] == [((150, 20), 40), ((150, 20), 5)]
    assert saved[0] is not frame
    assert np.array_equal(frame, image())
    namespace['_draw_tracking_marker'](frame, [SimpleNamespace()], 200, 100)
    assert len([call for call in cv.calls if call[0] == 'circle']) == 2


@pytest.mark.parametrize(
    'offset,pc,enabled,now,last_pub,last_real,expected_diagnostic',
    [
        (None, False, True, 10, 0, 0, 'no offset'),
        (0.4, False, True, 10, 9.95, 0, 'interval'),
        (0.4, True, False, 10, 0, 0, 'waiting for provider'),
        (0.4, True, True, 10, 0, 9.5, 'waiting for provider'),
    ],
)
def test_tracking_publish_gates_do_not_advance_clocks_or_emit(
    offset, pc, enabled, now, last_pub, last_real, expected_diagnostic, capsys
):
    namespace = functions(
        TRACKER,
        {'_maybe_publish_tracking', '_tracking_publish_diagnostic'},
        PUBLISH_IN_PC=enabled,
        PC_FALLBACK_SEC=1,
        _publish_tracking_offset=lambda *args: pytest.fail('publish gate bypassed'),
    )
    assert namespace['_maybe_publish_tracking'](offset, 'HAND', pc, now, last_pub, last_real, 0.1, False, None, {}) == (
        last_pub,
        last_real,
        False,
    )
    assert expected_diagnostic in capsys.readouterr().out


@pytest.mark.parametrize('observed,expected_skip', [(42.0, False), (None, True)])
def test_tracking_shared_fallback_retains_source_timestamp_and_identity_or_rejects_without_emission(
    observed, expected_skip
):
    messages = []
    namespace = functions(
        TRACKER,
        {'_maybe_publish_tracking', '_publish_tracking_offset', '_tracking_publish_diagnostic'},
        PUBLISH_IN_PC=True,
        PC_FALLBACK_SEC=1,
        pub=lambda topic, payload: messages.append((topic, payload)),
    )
    metadata = {'frame_id': 7, 'camera_session': 'capture-session'}
    guard = SimpleNamespace(source_time=lambda value: observed)
    result = namespace['_maybe_publish_tracking'](0.12345, 'HAND', True, 1000, 10, 10, 0.1, True, guard, metadata)
    assert result == ((10, 10, True) if expected_skip else (1000, 1000, False))
    if expected_skip:
        assert messages == []
    else:
        assert [topic for topic, payload in messages] == ['vision.tracking.offset', 'tracking.pose']
        first, second = (payload for topic, payload in messages)
        assert first == {'offset_x': 0.123, 'mode': 'hand', 'ts': 42, 'source': 'pc-fallback', **metadata}
        assert second == {
            'mode': 'hand',
            'target': {'x': 0.123, 'y': 0.0},
            'ts': 42,
            'source': 'pc-fallback',
            **metadata,
        }


def test_tracking_cleanup_stops_at_first_owner_error_and_warns(capsys):
    calls = []

    def close_stream():
        calls.append('stream')
        raise RuntimeError('stream close failed')

    namespace = functions(TRACKER, {'_close_tracking_detectors'})
    namespace['_close_tracking_detectors'](
        SimpleNamespace(close=close_stream),
        SimpleNamespace(close=lambda: calls.append('face')),
        SimpleNamespace(close=lambda: calls.append('hand')),
    )
    assert calls == ['stream']
    assert 'detector cleanup warning: stream close failed' in capsys.readouterr().out


@pytest.mark.parametrize(
    'topic,mode,active,expected_active,reset,consumed',
    [
        ('ai.mode', 'local_offload', False, True, True, False),
        ('vision.provider', 'pc', True, False, False, False),
        ('vision.provider', 'local', True, True, False, False),
        ('irrelevant', 'local', False, False, False, True),
    ],
)
def test_obstacle_provider_changes_reset_history_only_on_local_resume(
    topic, mode, active, expected_active, reset, consumed
):
    hist, times = deque([0.2]), deque([10.0])
    calls = []
    sub = SimpleNamespace(recv=lambda **kwargs: calls.append(kwargs) or (topic, {'mode': mode}))
    namespace = functions(
        OBSTACLE,
        {'_poll_obstacle_mode'},
        TOPIC_SYSTEM_AI_MODE_CHANGED='ai.mode',
        TOPIC_PROVIDER_VISION_STATE='vision.provider',
    )
    result = namespace['_poll_obstacle_mode'](sub, active, hist, times, True)
    assert result == (expected_active, not reset, consumed)
    assert list(hist) == ([] if reset else [0.2])
    assert list(times) == ([] if reset else [10.0])
    assert calls == [{'timeout_ms': 10}]


def test_obstacle_provider_absence_empty_message_and_receive_error_leave_history_unchanged(capsys):
    import sys

    namespace = functions(OBSTACLE, {'_poll_obstacle_mode'}, sys=sys)
    hist, times = deque([0.2]), deque([10.0])

    def fail(**kwargs):
        raise RuntimeError('temporary subscription error')

    for sub in (None, SimpleNamespace(recv=lambda **kwargs: ('', {})), SimpleNamespace(recv=fail)):
        assert namespace['_poll_obstacle_mode'](sub, True, hist, times, True) == (True, True, False)
    assert list(hist) == [0.2]
    assert list(times) == [10.0]
    assert 'temporary subscription error' in capsys.readouterr().err


def test_obstacle_paused_snapshot_carries_explicit_non_ready_state_without_bus_observation():
    events = []
    namespace = functions(
        OBSTACLE,
        {'_write_paused_obstacle'},
        ROI_Y0=0.45,
        ROI_H=0.3,
        OBSTACLE_JSON='/fake/obstacle.json',
        now_s=lambda: 100,
        copy_raw_snapshot=lambda text: events.append(('snapshot', text)),
        atomic_write_json=lambda path, payload: events.append(('write', path, payload)),
    )
    namespace['_write_paused_obstacle']()
    assert events[0] == ('snapshot', 'PC offload')
    payload = events[1][2]
    assert events[1][1] == '/fake/obstacle.json'
    assert payload['present'] is False
    assert payload['data_ready'] is False
    assert payload['observed_at'] is None
    assert payload['error'] == 'local_detector_paused'
    assert payload['source'] == 'pc_offload'
    assert payload['roi_norm'] == {'y0': 0.45, 'h': 0.3}


@pytest.mark.parametrize('ready', [True, False])
def test_obstacle_derived_snapshot_preserves_capture_time_and_invalidates_faulted_file(ready):
    calls = []
    frame = image()
    namespace = functions(
        OBSTACLE,
        {'_save_stream_obstacle_image'},
        PROC_PATH='/fake/proc.jpg',
        cv2=SimpleNamespace(
            IMWRITE_JPEG_QUALITY=1, imwrite=lambda path, frame, args: calls.append(('write', path, args))
        ),
        os=SimpleNamespace(utime=lambda *args: calls.append(('timestamp', *args))),
        Path=lambda path: SimpleNamespace(exists=lambda: True),
    )
    namespace['_save_stream_obstacle_image'](frame, {'ready': ready}, 42.0)
    assert calls[-1] == ('timestamp', '/fake/proc.jpg', (42.0, 42.0) if ready else (0, 0))
    assert len(calls) == (2 if ready else 1)


def test_obstacle_snapshot_timestamp_error_is_reported_without_retry(capsys):
    calls = []

    def fail(path, times):
        calls.append((path, times))
        raise OSError('timestamp denied')

    namespace = functions(
        OBSTACLE,
        {'_save_stream_obstacle_image'},
        PROC_PATH='/fake/proc.jpg',
        Path=lambda path: SimpleNamespace(exists=lambda: True),
        os=SimpleNamespace(utime=fail),
    )
    namespace['_save_stream_obstacle_image'](image(), {'ready': False}, None)
    assert calls == [('/fake/proc.jpg', (0, 0))]
    assert 'timestamp denied' in capsys.readouterr().out


def test_obstacle_file_fallback_loads_raw_after_processed_image_without_forging_source_time():
    calls = []
    proc, raw = image(), image()

    def load(path):
        calls.append(path)
        return proc if path.endswith('proc.jpg') else raw

    namespace = functions(
        OBSTACLE,
        {'_receive_obstacle_frame'},
        PROC_PATH='/fake/proc.jpg',
        RAW_PATH='/fake/raw.jpg',
        file_mtime_age=lambda path: (42, 0.75),
        load_gray=load,
        _publish_missing_obstacle=lambda *args: pytest.fail('existing proc frame reported missing'),
    )
    sample = namespace['_receive_obstacle_frame'](None)
    assert sample[0] is proc
    assert sample[1] is raw
    assert sample[2:] == (42, 0.75, {'observed_at': 42})
    assert calls == ['/fake/proc.jpg', '/fake/raw.jpg']


def test_obstacle_annotation_bin_failure_keeps_summary_overlay():
    overlays = []

    def bad_bins(*args):
        raise ValueError('empty roi')

    namespace = functions(
        OBSTACLE,
        {'_annotate_obstacle'},
        OBST_ANN=True,
        OBST_BINS=4,
        OBST_ANN_PATH='/fake/annotated.jpg',
        bins_edge_pcts=bad_bins,
        draw_overlay=lambda **kwargs: overlays.append(kwargs),
    )
    frame, sl = image(), slice(45, 75)
    namespace['_annotate_obstacle'](frame, sl, True, 0.7, 0.2)
    assert overlays[0]['base_gray'] is frame
    assert overlays[0]['sl'] == sl
    assert overlays[0]['bins_pcts'] is None
    assert overlays[0]['confidence'] == 0.7
    assert overlays[0]['ann_path'] == '/fake/annotated.jpg'
    namespace['OBST_ANN'] = False
    namespace['_annotate_obstacle'](frame, sl, False, 0, 0)
    assert len(overlays) == 1
