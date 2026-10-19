"""Legacy face API backed by the shared controller; one bounded worker on demand."""

from __future__ import annotations

import copy
import os
import threading
import time
from io import BytesIO

from apps.ui.face.catalog import CATALOG, descriptors, get_settings, settings_path
from apps.ui.face.controller import FaceController
from apps.ui.face.schema import EXPRESSIONS, number
from common.secure_files import atomic_write

FACE_CLOSE_ERROR_PREFIX = "face_close_failed:"
OUT_LATEST = os.getenv("FACE_LATEST_PATH", "/tmp/face_latest.png")
OUT_LEGACY = os.getenv("FACE_LEGACY_PATH", "/tmp/face_runtime.png")
DEFAULT_SINK = os.getenv("FACE_SINK", "file").strip().lower()
ALLOWED = EXPRESSIONS | {"blink"}
SINKS = {"file", "lcd", "null"}
_STATE_LOCK = threading.RLock()
_CONTROL_LOCK = threading.RLock()
STATE = {
    "playing": False,
    "running": False,
    "expr": "neutral",
    "fps": 12,
    "started_ts": None,
    "last_ts": None,
    "frame_count": 0,
    "_last_payload": None,
    "error": None,
    "sink": DEFAULT_SINK,
}
LcdNotAvailable = RuntimeError


class FaceSink:
    def present(self, image):
        raise NotImplementedError

    def close(self):
        return None


class NullSink(FaceSink):
    def present(self, image):
        return None


class FileSink(FaceSink):
    def __init__(self, path=OUT_LATEST):
        self.path, self._written = path, False

    def present(self, image):
        # Legacy artifact is a snapshot; streaming previews use bounded memory.
        if not self._written:
            atomic_write(self.path, lambda stream: image.save(stream, "PNG"))
            self._written = True


def _make_sink():
    kind = STATE.get("sink", DEFAULT_SINK)
    if kind == "lcd":
        from apps.ui.face.lcd_sink import LcdSink

        def report(**fields):
            from services.api_core.devices import observe_lcd

            observe_lcd(
                {
                    "source": "face-runtime",
                    "observed_at": time.time(),
                    "lcd": {**fields, "confirmation": "control_write_accepted", "physical_validity": "unverified"},
                }
            )

        return LcdSink(report=report)
    return FileSink(OUT_LATEST) if kind == "file" else NullSink()


class _Animator:
    def __init__(self):
        self._thr = None
        self._stop = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest = self._png = None
        self._version = 0
        self.controller = None
        self.activity = 0
        self._requested_fps = 12

    def start(self):
        self._stop.clear()
        with self._frame_lock:
            self._latest = self._png = None
        self._thr = threading.Thread(target=self._loop, name="face-anim", daemon=True)
        self._thr.start()

    def stop(self):
        self._stop.set()
        if self._thr and self._thr is not threading.current_thread():
            self._thr.join(timeout=3.5)

    def latest_png(self):
        with self._frame_lock:
            if self._latest is None:
                return None
            if self._png is None:
                buffer = BytesIO()
                self._latest.save(buffer, "PNG")
                self._png = buffer.getvalue()
            return self._png

    def _refresh_settings(self, controller, previous):
        path = settings_path()
        stat = path.stat() if path.exists() else None
        stamp = (str(path), stat.st_mtime_ns if stat else None)
        if stamp != previous:
            with _STATE_LOCK:
                controller.configure(get_settings())
        return stamp

    def _expired(self, controller, started, tick):
        with _STATE_LOCK:
            duration = (STATE.get("_last_payload") or {}).get("duration_s", 0)
        return (
            duration and tick - started >= duration or controller.power_mode == "battery" and tick - self.activity >= 45
        )

    def _present_tick(self, sink, controller, fps):
        render_started = time.perf_counter()
        with _STATE_LOCK:
            image = controller.frame_image()
            changed = controller.renderer.last_changed
        render_ms = (time.perf_counter() - render_started) * 1000
        present_ms = 0.0
        if changed:
            present_started = time.perf_counter()
            sink.present(image)
            present_ms = (time.perf_counter() - present_started) * 1000
            with self._frame_lock:
                self._latest, self._png = image, None
                self._version += 1
            if isinstance(sink, NullSink) and STATE["frame_count"] == 0:
                FileSink(OUT_LATEST).present(image)
            with _STATE_LOCK:
                STATE["frame_count"] += 1
                STATE["last_present_ms"] = round(present_ms, 3)
        with _STATE_LOCK:
            STATE.update(
                last_ts=time.time(),
                fps=fps,
                style=controller.renderer.style,
                skin=controller.renderer.skin,
                power_mode=controller.power_mode,
                channels=controller.anim.owners,
                render_ms=round(render_ms, 3),
                present_ms=round(present_ms, 3),
            )

    def _close_resources(self, sink, controller):
        try:
            power = sink.close()
            if isinstance(power, dict):
                with _STATE_LOCK:
                    STATE["lcd_power"] = power
        except Exception as error:
            with _STATE_LOCK:
                STATE["error"] = FACE_CLOSE_ERROR_PREFIX + str(error)
        finally:
            with _STATE_LOCK:
                try:
                    controller.close()
                except Exception as error:
                    STATE["error"] = FACE_CLOSE_ERROR_PREFIX + str(error)
                finally:
                    STATE.update(playing=False, running=False)

    def _loop(self):
        sink = self._sink
        controller = self.controller
        started = time.monotonic()
        settings_stamp = None
        next_settings = started
        with _STATE_LOCK:
            STATE.update(running=True, started_ts=time.time(), frame_count=0)
        try:
            while not self._stop.is_set():
                tick = time.monotonic()
                if tick >= next_settings:
                    settings_stamp = self._refresh_settings(controller, settings_stamp)
                    next_settings = tick + 1
                limit = descriptors()["fps"][controller.power_mode]
                fps = min(self._requested_fps, limit)
                if self._expired(controller, started, tick):
                    break
                self._present_tick(sink, controller, fps)
                self._stop.wait(max(0, 1 / fps - (time.monotonic() - tick)))
        except Exception as error:
            with _STATE_LOCK:
                STATE["error"] = type(error).__name__ + ":" + str(error)
        finally:
            self._close_resources(sink, controller)

    def _audio_command(self, body):
        playing = body.get("playing", True)
        if type(playing) is not bool:
            raise ValueError("invalid_audio_state")
        self.controller.audio_envelope(body.get("level", 0), playing=playing)

    def _gesture_command(self, body):
        key = body.get("id")
        if not isinstance(key, str) or not self.controller.do(key):
            raise ValueError("gesture_not_active")

    def _expression_command(self, body, intent):
        expr = body.get("expr", "curious" if intent == "listening" else "calm")
        if not isinstance(expr, str) or expr not in EXPRESSIONS:
            raise ValueError("invalid_expression")
        self.controller.set_expr(expr)
        STATE["expr"] = expr

    def command(self, body):
        with _STATE_LOCK:
            if not STATE["playing"] or not self.controller:
                raise ValueError("face_not_running")
            intent = body.get("intent")
            if intent == "audio":
                self._audio_command(body)
            elif intent == "gesture":
                self._gesture_command(body)
            elif intent in {"mood", "listening", "waiting"}:
                self._expression_command(body, intent)
            else:
                raise ValueError("unknown_face_intent")
            self.activity = time.monotonic()
        return get_state()


_anim = _Animator()


def _play_options(payload):
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    expr = payload.get("expr", "neutral")
    if not isinstance(expr, str) or expr not in ALLOWED:
        raise ValueError("invalid_expression")
    fps = int(number(payload.get("fps", 12), 1, 60))
    duration = number(payload.get("duration_s", 0), 0, 300)
    sink = payload.get("sink", os.getenv("FACE_SINK", DEFAULT_SINK))
    if sink not in SINKS:
        raise ValueError("invalid_face_sink")
    key = payload.get("gesture_id")
    if key is not None and (not isinstance(key, str) or CATALOG.get(key) is None):
        raise ValueError("unknown_gesture")
    settings = get_settings()
    if key and key not in settings["active_gestures"]:
        raise ValueError("gesture_not_active")
    return expr, fps, duration, sink, key


def _play_controller(settings, expr, key):
    controller = FaceController(style=settings["style"], idle=settings["idle"], power_mode=settings["power_mode"])
    controller.configure(settings)
    controller.set_expr(expr)
    if key and not controller.do(key):
        raise ValueError("gesture_not_active")
    return controller


def _play_sink(sink, controller, prepare_lcd):
    with _STATE_LOCK:
        STATE["sink"] = sink
    try:
        if sink == "lcd" and prepare_lcd is not None:
            prepare_lcd()
        target = _make_sink()
    except BaseException:
        controller.close()
        raise
    return target


def _play_error(error):
    unavailable = (
        isinstance(error, (OSError, ImportError)) or isinstance(error, RuntimeError) and "lcd_" not in str(error)
    )
    code = "lcd_unavailable" if unavailable else str(error)
    with _STATE_LOCK:
        if not STATE["playing"]:
            STATE["error"] = code
    return {
        "ok": False,
        "error": code,
        "detail": str(error),
        "status": 503 if unavailable else 409 if "lcd_" in code else 400,
    }


def play(payload, *, prepare_lcd=None):
    try:
        expr, fps, duration, sink, key = _play_options(payload)
        with _CONTROL_LOCK:
            stop({})
            if _anim._thr and _anim._thr.is_alive():
                return {"ok": False, "error": "face_stopping", "status": 409}
            settings = get_settings()
            controller = _play_controller(settings, expr, key)
            target = _play_sink(sink, controller, prepare_lcd)
            _anim.controller, _anim._sink = controller, target
            _anim._requested_fps, _anim.activity = fps, time.monotonic()
            with _STATE_LOCK:
                STATE.update(
                    playing=True,
                    error=None,
                    lcd_power=None,
                    expr=expr,
                    fps=min(fps, descriptors()["fps"][settings["power_mode"]]),
                    _last_payload={**payload, "duration_s": duration},
                )
            _anim.start()
        return get_state()
    except (ValueError, TypeError, OSError, RuntimeError, ImportError) as error:
        return _play_error(error)


def stop(_payload=None):
    with _CONTROL_LOCK:
        _anim.stop()
        if not _anim._thr or not _anim._thr.is_alive():
            with _STATE_LOCK:
                STATE.update(playing=False, running=False)
        result = get_state()
        if _anim._thr and _anim._thr.is_alive():
            result.update(ok=False, error="face_stopping", status=409)
        elif (result["state"].get("error") or "").startswith(FACE_CLOSE_ERROR_PREFIX):
            result.update(ok=False, error="face_close_failed", status=503)
        elif (result["state"].get("lcd_power") or {}).get("ok") is False:
            result.update(ok=False, error="lcd_off_unconfirmed", status=503)
        return result


def get_state():
    with _STATE_LOCK:
        return {"ok": True, "state": copy.deepcopy(STATE), "actuation": False}


def latest_png():
    with _STATE_LOCK:
        if not STATE.get("playing") or not STATE.get("running"):
            return None
    return _anim.latest_png()


def command(body):
    if not isinstance(body, dict):
        raise ValueError("invalid_face_intent")
    return _anim.command(body)
