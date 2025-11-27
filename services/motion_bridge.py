#!/usr/bin/env python3
from __future__ import annotations

"""
Rider-Pi – Motion Bridge (deadman auto-stop + debounce + RX echo + compat adapter)

Kluczowe punkty:
- Konwencja skrętu: yaw<0 => left, yaw>0 => right (spójne z web_motion_bridge).
- Debounce i DROP_OLD_MS jak wcześniej; SAFE_MAX_DURATION zabezpiecza deadmana.
- Poprawione wygładzanie kątów (wrap-around 0/360) — interpolacja robiona w przestrzeni "unwrapped".
- Deadman publikuje poprawnie rid; sygnatura _schedule_deadman(d, rid=None).
- Defensywność wywołań HW i publikacji.

Słucha:
  * NOWE:  cmd.move {vx,vy,yaw|az,duration,ts}, cmd.stop {}
  * STARE: cmd.motion.forward/backward/left/right/turn_left/turn_right/stop {speed,runtime}
Mapuje na wywołania XGO; skręt na vendorowe turnleft/turnright(step).
Publikuje:
  * motion.bridge.event {event, detail}
  * devices.xgo {...}

ENV (wycinek):
- BUS_PUB_PORT=5555, BUS_SUB_PORT=5556
- DRY_RUN=1, BRIDGE_READONLY=1
- PREEMPT=1, DROP_OLD_MS=200, DEADMAN_MS=220
- BUS_RCVHWM=100, BUS_CONFLATE=0
"""

import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import signal  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from collections.abc import Callable  # noqa: E402
from threading import Timer  # noqa: E402
from typing import Any  # noqa: E402

import zmq  # type: ignore  # noqa: E402

# --- Load motion bridge configuration ---
try:
    from apps.motion.config import load_motion_bridge_config

    _motion_cfg = load_motion_bridge_config()
    XGO_PORT = _motion_cfg.serial_port
except (ImportError, ModuleNotFoundError):
    # Fallback to ENV if config module unavailable
    XGO_PORT = os.getenv("XGO_PORT", "/dev/ttyAMA0")

# --- ENV / parametry ---
BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
DRY_RUN = os.getenv("DRY_RUN", "1") == "1"
BRIDGE_READONLY = os.getenv("BRIDGE_READONLY", "1") == "1"
XGO_LAZY_OPEN = os.getenv("XGO_LAZY_OPEN", "1") == "1"
BRIDGE_RATE_HZ = max(0.1, min(20.0, float(os.getenv("BRIDGE_RATE_HZ", "2"))))

SPEED_LINEAR = float(os.getenv("SPEED_LINEAR", "12"))
SAFE_MAX_DURATION = float(os.getenv("SAFE_MAX_DURATION", "0.6"))
MIN_CMD_GAP = float(os.getenv("MIN_CMD_GAP", "0.10"))

TURN_STEP_MIN = int(os.getenv("TURN_STEP_MIN", "20"))
TURN_STEP_MAX = int(os.getenv("TURN_STEP_MAX", "70"))

# Stabilizacja yaw
YAW_DEADBAND_DPS = float(os.getenv("YAW_DEADBAND_DPS", "0.8"))
YAW_SMOOTH_ALPHA = max(0.0, min(1.0, float(os.getenv("YAW_SMOOTH_ALPHA", "0.2"))))
YAW_FREEZE_WHEN_IDLE_S = float(os.getenv("YAW_FREEZE_WHEN_IDLE_S", "2.0"))
YAW_IDLE_MAX_DPS = float(os.getenv("YAW_IDLE_MAX_DPS", "8.0"))

# Anty-lag / preempcja
PREEMPT = os.getenv("PREEMPT", "1") == "1"
DROP_OLD_MS = float(os.getenv("DROP_OLD_MS", "200"))
DEADMAN_MS = float(os.getenv("DEADMAN_MS", "0"))  # 0 = użyj duration

# Ile wiadomości SUB przetwarzać na jeden tick (FIFO)
MAX_MSGS_PER_TICK = int(os.getenv("MAX_MSGS_PER_TICK", "10"))

MOVES_ALLOWED = (not DRY_RUN) and (not BRIDGE_READONLY)


# --- helpery kątów ---
def _norm360(deg: float | None) -> float | None:
    if deg is None:
        return None
    try:
        x = float(deg) % 360.0
        return x if x >= 0.0 else x + 360.0
    except Exception:
        return None


def _angle_diff_deg(a: float, b: float) -> float:
    """Różnica kątów (a-b) w zakresie (-180, 180]."""
    return (a - b + 180.0) % 360.0 - 180.0


# Stan filtra yaw
_yaw_state = {"ts": None, "yaw_raw": None, "yaw_stable": None, "src": "gyro_stabilized"}
_last_motion_cmd_ts = 0.0


def _stabilize_yaw(yaw_raw: float | None, ts: float, freeze: bool = False) -> tuple[float | None, float | None, str]:
    """Wygładzanie yaw z poprawną obsługą wrap-aroundu 0/360."""
    global _yaw_state
    if yaw_raw is None:
        _yaw_state["ts"] = ts
        return None, None, _yaw_state["src"]

    prev_ts, prev_raw, prev_stab = (
        _yaw_state["ts"],
        _yaw_state["yaw_raw"],
        _yaw_state["yaw_stable"],
    )

    if prev_ts is not None and prev_raw is not None:
        dt = max(1e-6, ts - float(prev_ts))
        yaw_rate = (float(yaw_raw) - float(prev_raw)) / dt
    else:
        yaw_rate = 0.0

    base_heading = _norm360(yaw_raw)

    if prev_stab is None or base_heading is None:
        stab = base_heading
    else:
        if freeze or abs(yaw_rate or 0.0) < YAW_DEADBAND_DPS:
            stab = prev_stab
        else:
            # policz minimalny krok do base_heading względem poprzedniego stabilnego kąta
            step = _angle_diff_deg(base_heading, prev_stab)
            # UWAGA: nie składamy do [0,360) przed interpolacją!
            raw_next_unwrapped = prev_stab + step
            if YAW_SMOOTH_ALPHA <= 0.0:
                stab = raw_next_unwrapped
            elif YAW_SMOOTH_ALPHA >= 1.0:
                stab = raw_next_unwrapped
            else:
                stab = prev_stab + YAW_SMOOTH_ALPHA * (raw_next_unwrapped - prev_stab)
            stab = _norm360(stab)

    _yaw_state["ts"] = ts
    _yaw_state["yaw_raw"] = yaw_raw
    _yaw_state["yaw_stable"] = stab
    return stab, yaw_rate, _yaw_state["src"]


# --- Opcjonalny sterownik XGO (leniwe otwieranie) ---
_xgo_cls = None
try:
    from xgolib import XGO as _XGO  # type: ignore

    _xgo_cls = _XGO
except Exception:
    _xgo_cls = None

xgo = None


def ensure_xgo_open() -> Any | None:
    global xgo
    if xgo is not None:
        return xgo
    if _xgo_cls is None:
        return None
    try:
        xgo = _xgo_cls(port=XGO_PORT)
        return xgo
    except Exception as e:
        print("[bridge] XGO open failed:", e, flush=True)
        return None


def _list_hw_methods() -> list[str]:
    try:
        dev = xgo or ensure_xgo_open()
        if not dev:
            return []
        return [m for m in dir(dev) if not m.startswith("_")]
    except Exception:
        return []


# --- ZMQ ---
ctx = zmq.Context.instance()
pub = ctx.socket(zmq.PUB)
pub.connect(f"tcp://127.0.0.1:{BUS_PUB_PORT}")

sub = ctx.socket(zmq.SUB)
# FIFO (bez "latest only"): wysoka HWM, bez conflation
try:
    sub.setsockopt(zmq.RCVHWM, int(os.getenv("BUS_RCVHWM", "100")))
    if os.getenv("BUS_CONFLATE", "0") == "1":
        sub.setsockopt(zmq.CONFLATE, 1)
except Exception:
    pass

sub.connect(f"tcp://127.0.0.1:{BUS_SUB_PORT}")
for t in [
    "cmd.motion.forward",
    "cmd.motion.backward",
    "cmd.motion.left",
    "cmd.motion.right",
    "cmd.motion.turn_left",
    "cmd.motion.turn_right",
    "cmd.motion.stop",
    "cmd.motion.demo",
    "cmd.move",
    "cmd.stop",
    "cmd.balance",
    "cmd.height",
    "motion.cmd",
]:
    sub.setsockopt_string(zmq.SUBSCRIBE, t)

# anti slow-joiner
time.sleep(0.3)


def _pub_json(topic: str, payload: dict):
    try:
        pub.send_string(f"{topic} {json.dumps(payload, ensure_ascii=False)}")
    except Exception:
        pass


def publish_event(name: str, detail: dict):
    payload = {"ts": time.time(), "event": name, "detail": (detail or {})}
    _pub_json("motion.bridge.event", payload)
    print(f"[bridge] {name}: {detail}", flush=True)


# --- Telemetria: devices.xgo ---
def _sanitize_angle(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        cleaned = re.sub(r"[^0-9+\-.]", "", s)
        try:
            return float(cleaned)
        except Exception:
            return None
    try:
        return float(val)
    except Exception:
        return None


def _get_val(names: list[str], post: Callable[[Any], Any] | None = None) -> Any:
    dev = xgo or ensure_xgo_open()
    if not dev:
        return None
    for n in names:
        fn = getattr(dev, n, None)
        if callable(fn):
            try:
                v = fn()
                return post(v) if post else v
            except Exception:
                continue
    return None


def _read_attitude():
    dev = xgo or ensure_xgo_open()
    if not dev:
        return (None, None, None, "gyro_stabilized")

    def _axis(names):
        return _get_val(names, _sanitize_angle)

    roll = _axis(["read_roll", "rider_read_roll"])
    pitch = _axis(["read_pitch", "rider_read_pitch"])
    yaw_raw = _axis(["read_yaw", "rider_read_yaw"])
    src = "gyro_stabilized"

    for m in ("read_heading", "rider_read_heading", "heading", "read_yaw_deg360"):
        fn = getattr(dev, m, None)
        if not callable(fn):
            continue
        try:
            yaw_raw = float(fn())
            src = "heading_native"
            break
        except Exception:
            continue

    if roll is None or pitch is None or yaw_raw is None:
        imu_vec = None
        for n in ("read_imu", "read_imu_int16", "rider_read_imu_int16"):
            fn = getattr(dev, n, None)
            if not callable(fn):
                continue
            try:
                imu_vec = fn()
            except Exception:
                imu_vec = None
            if isinstance(imu_vec, (list, tuple)) and len(imu_vec) >= 3:
                break
            imu_vec = None
        if isinstance(imu_vec, (list, tuple)) and len(imu_vec) >= 9:

            def _rad_to_deg(val):
                try:
                    f = float(val)
                except Exception:
                    return None
                if abs(f) <= math.pi * 2 + 1e-3:
                    return math.degrees(f)
                return f

            if roll is None:
                roll = _rad_to_deg(imu_vec[6])
            if pitch is None:
                pitch = _rad_to_deg(imu_vec[7])
            if yaw_raw is None:
                yaw_raw = _rad_to_deg(imu_vec[8])
                src = "gyro_stabilized"

    return (roll, pitch, yaw_raw, src)


def read_xgo_telemetry() -> dict:
    xgo if xgo is not None else (ensure_xgo_open() if not XGO_LAZY_OPEN else xgo)
    batt = _get_val(["rider_read_battery", "read_battery"])
    fw = _get_val(["rider_read_firmware", "read_firmware", "version"])
    roll, pitch, yaw_raw, yaw_src = _read_attitude()
    ts = time.time()

    if yaw_src == "heading_native":
        yaw_norm = _norm360(yaw_raw)
        yaw_rate = None
        yaw_out = yaw_norm
        src_out = "heading_native"
    else:
        prev_ts, prev_raw = _yaw_state["ts"], _yaw_state["yaw_raw"]
        if prev_ts is not None and prev_raw is not None and yaw_raw is not None:
            dt_est = max(1e-6, ts - float(prev_ts))
            yaw_rate_est = (float(yaw_raw) - float(prev_raw)) / dt_est
        else:
            yaw_rate_est = 0.0
        idle_for = ts - (_last_motion_cmd_ts or 0.0)
        freeze = (idle_for >= YAW_FREEZE_WHEN_IDLE_S) and (abs(yaw_rate_est) < YAW_IDLE_MAX_DPS)
        yaw_stable, yaw_rate, _ = _stabilize_yaw(yaw_raw, ts, freeze=freeze)
        yaw_out, src_out = yaw_stable, "gyro_stabilized"

    pose_axes = None
    if any(v is not None for v in (roll, pitch, yaw_out)):
        pose_axes = {"x": roll, "y": pitch, "z": yaw_out}

    return {
        "present": bool(xgo is not None),
        "imu_ok": (roll is not None and pitch is not None and yaw_raw is not None),
        "pose": pose_axes,
        "battery_pct": float(batt) if batt is not None else None,
        "roll": roll,
        "pitch": pitch,
        "yaw_raw": yaw_raw,
        "yaw": yaw_out,
        "yaw_rate_dps": yaw_rate,
        "yaw_src": src_out,
        "fw": fw,
        "ts": ts,
    }


_last_telem_print = 0.0


def publish_devices_xgo(payload: dict):
    global _last_telem_print
    _pub_json("devices.xgo", payload)
    now = time.time()
    if now - _last_telem_print >= 2.0:
        print("[bridge] devices.xgo ->", payload, flush=True)
        _last_telem_print = now


# --- Deadman (autostop po czasie) ---
_deadman_lock = threading.Lock()
_deadman_timer: Timer | None = None


def _cancel_deadman():
    global _deadman_timer
    with _deadman_lock:
        if _deadman_timer is not None:
            try:
                _deadman_timer.cancel()
            except Exception:
                pass
        _deadman_timer = None


def _schedule_deadman(duration_s: float, rid: str | None = None):
    """Planowany auto-stop po czasie (lub DEADMAN_MS)."""
    global _deadman_timer
    if DEADMAN_MS and DEADMAN_MS > 0:
        d = float(DEADMAN_MS) / 1000.0
    else:
        d = max(0.05, min(float(duration_s or 0.0), SAFE_MAX_DURATION))
    _cancel_deadman()

    def _fire():
        try:
            if ensure_xgo_open():
                try:
                    xgo.stop()  # type: ignore[attr-defined]
                except Exception as e:
                    print("[bridge] hw call error:", e, flush=True)
            publish_event("auto_stop", {"after_s": d, "rid": rid})
        except Exception:
            pass

    t = Timer(d, _fire)
    t.daemon = True
    with _deadman_lock:
        _deadman_timer = t
    t.start()


# --- Helpery wywołań HW ---
def _try_call(fn, *args) -> bool:
    try:
        fn(*args)
        return True
    except TypeError:
        return False
    except Exception as e:
        print("[bridge] hw call error:", e, flush=True)
        return True


def _call_move(method_name: str, *args):
    if not MOVES_ALLOWED:
        return
    dev = ensure_xgo_open()
    if not dev:
        print("[bridge] hw unavailable for", method_name, flush=True)
        return
    fn = getattr(dev, method_name, None)
    if not callable(fn):
        print(f"[bridge] hw call missing method: {method_name}", flush=True)
        return
    _try_call(fn, *args)


def _clamp01(v: float) -> float:
    try:
        v = float(v)
    except Exception:
        return 0.0
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def _yaw_to_step(yaw_abs_01: float) -> int:
    s = _clamp01(yaw_abs_01)
    step = int(round(TURN_STEP_MIN + s * (TURN_STEP_MAX - TURN_STEP_MIN)))
    return max(TURN_STEP_MIN, min(TURN_STEP_MAX, step))


def do_forward(speed_norm, runtime):
    if not MOVES_ALLOWED:
        return
    spd = SPEED_LINEAR * _clamp01(abs(speed_norm))
    print(f"[bridge] forward v={spd:.2f} t={runtime:.2f}")
    dev = ensure_xgo_open()
    if dev and hasattr(dev, "forward"):
        if not _try_call(dev.forward, spd):
            if not _try_call(dev.forward, runtime):
                _try_call(dev.forward, spd, runtime)


def do_backward(speed_norm, runtime):
    if not MOVES_ALLOWED:
        return
    spd = SPEED_LINEAR * _clamp01(abs(speed_norm))
    print(f"[bridge] backward v={spd:.2f} t={runtime:.2f}")
    dev = ensure_xgo_open()
    if dev:
        meth = "back" if hasattr(dev, "back") else ("backward" if hasattr(dev, "backward") else None)
        if meth:
            if not _try_call(getattr(dev, meth), spd):
                if not _try_call(getattr(dev, meth), runtime):
                    _try_call(getattr(dev, meth), spd, runtime)


def do_turn_left(yaw_abs_norm, runtime):
    step = _yaw_to_step(yaw_abs_norm)
    print(f"[bridge] turn_left step={step} t={runtime:.2f}")
    _call_move("turnleft", step)


def do_turn_right(yaw_abs_norm, runtime):
    step = _yaw_to_step(yaw_abs_norm)
    print(f"[bridge] turn_right step={step} t={runtime:.2f}")
    _call_move("turnright", step)


def do_strafe_left(speed_norm, runtime):
    spd = SPEED_LINEAR * _clamp01(abs(speed_norm))
    print(f"[bridge] left (strafe) v={spd:.2f} t={runtime:.2f}")
    _call_move("left", spd)


def do_strafe_right(speed_norm, runtime):
    spd = SPEED_LINEAR * _clamp01(abs(speed_norm))
    print(f"[bridge] right (strafe) v={spd:.2f} t={runtime:.2f}")
    _call_move("right", spd)


def do_stop():
    print("[bridge] stop")
    _cancel_deadman()
    if ensure_xgo_open():
        try:
            xgo.stop()  # type: ignore[attr-defined]
        except Exception as e:
            print("[bridge] hw call error:", e, flush=True)


# --- sygnały, start ---
_running = True


def _sigterm(*_):
    global _running
    _running = False


signal.signal(signal.SIGINT, _sigterm)
signal.signal(signal.SIGTERM, _sigterm)

if not XGO_LAZY_OPEN:
    ensure_xgo_open()

print(
    "[bridge] START "
    f"(PUB:{BUS_PUB_PORT} SUB:{BUS_SUB_PORT} "
    f"DRY_RUN={bool(DRY_RUN)} READONLY={bool(BRIDGE_READONLY)} "
    f"MOVES_ALLOWED={bool(MOVES_ALLOWED)} LAZY={bool(XGO_LAZY_OPEN)} "
    f"RATE_HZ={BRIDGE_RATE_HZ} PORT={XGO_PORT} "
    f"SAFE_MAX={SAFE_MAX_DURATION}s MIN_GAP={MIN_CMD_GAP}s)",
    flush=True,
)
print("[bridge] hw methods:", ", ".join(_list_hw_methods()), flush=True)
publish_event("ready", {"ts": time.time()})

_last_cmd_ts = 0.0
_next_telem_ts = 0.0

# --- pętla główna ---
tick_dt = 0.01
while _running:
    now = time.time()

    # Telemetria
    if now >= _next_telem_ts:
        publish_devices_xgo(read_xgo_telemetry())
        _next_telem_ts = now + (1.0 / BRIDGE_RATE_HZ)

    # Odbiór komend – pobierz do N wiadomości i przetwarzaj KAŻDĄ (FIFO)
    batch: list[list[str]] = []
    for _ in range(MAX_MSGS_PER_TICK):
        try:
            frames = sub.recv_multipart(flags=zmq.NOBLOCK)
            batch.append([f.decode("utf-8", "ignore") for f in frames])
        except zmq.Again:
            break
        except Exception as e:
            print("[bridge] recv error:", e, flush=True)
            break

    if not batch:
        time.sleep(tick_dt)
        continue

    for frames in batch:
        if not frames:
            continue
        if len(frames) == 1:
            msg = frames[0]
            if " " in msg:
                topic, payload = msg.split(" ", 1)
            else:
                topic, payload = msg, "{}"
        else:
            topic = frames[0]
            payload = frames[1] if len(frames) == 2 else " ".join(frames[1:])

        try:
            data = json.loads(payload) if payload else {}
        except Exception:
            data = {}

        # LEGACY: dashboard 8080 publikuje na "motion.cmd"
        if topic == "motion.cmd":
            # payload np.: {"dir":"forward","v":0.22,"t":0.25,"rid":"...","ts":...}
            rid = data.get("rid")
            d = (data.get("dir") or "").lower()
            vx = float(data.get("v", 0.0) or 0.0)
            dur = max(
                0.05,
                min(
                    float(data.get("t", SAFE_MAX_DURATION) or SAFE_MAX_DURATION),
                    SAFE_MAX_DURATION,
                ),
            )
            publish_event(
                "rx_cmd.legacy",
                {"rid": rid, "topic": "motion.cmd", "dir": d, "v": vx, "t": dur},
            )

            now2 = time.time()
            ts_in = data.get("ts")
            if ts_in:
                try:
                    age = (now2 - float(ts_in)) * 1000.0
                    if age > DROP_OLD_MS:
                        publish_event(
                            "skip_cmd.move",
                            {"rid": rid, "reason": "drop_old", "age_ms": round(age, 1)},
                        )
                        continue
                except Exception:
                    pass

            if (now2 - _last_cmd_ts) < MIN_CMD_GAP:
                publish_event(
                    "skip_cmd.move",
                    {
                        "rid": rid,
                        "reason": "min_gap",
                        "gap_s": round(now2 - _last_cmd_ts, 3),
                    },
                )
                continue
            _last_cmd_ts = now2

            if PREEMPT:
                _cancel_deadman()
                if ensure_xgo_open():
                    try:
                        xgo.stop()  # type: ignore[attr-defined]
                    except Exception as e:
                        print("[bridge] hw call error (preempt stop):", e, flush=True)

            moved = False
            if d in ("forward", "fwd", "up"):
                moved = True
                do_forward(abs(vx), dur)
                publish_event("forward", {"rid": rid, "v": abs(vx), "runtime": dur})
            elif d in ("backward", "back", "down"):
                moved = True
                do_backward(abs(vx), dur)
                publish_event("backward", {"rid": rid, "v": abs(vx), "runtime": dur})
            elif d in ("left", "turn_left"):
                moved = True
                do_turn_left(abs(vx), dur)
                publish_event(
                    "turn_left",
                    {"rid": rid, "step": _yaw_to_step(abs(vx)), "runtime": dur},
                )
            elif d in ("right", "turn_right"):
                moved = True
                do_turn_right(abs(vx), dur)
                publish_event(
                    "turn_right",
                    {"rid": rid, "step": _yaw_to_step(abs(vx)), "runtime": dur},
                )
            elif d in ("stop", "halt"):
                do_stop()
                publish_event("stop", {"rid": rid})
                _last_motion_cmd_ts = time.time()
                continue
            else:
                publish_event("skip_cmd.move", {"rid": rid, "reason": "bad_dir", "dir": d})
                continue

            if moved:
                _last_motion_cmd_ts = now2
                _schedule_deadman(dur, rid)
            continue

        # NOWE: cmd.move / cmd.stop
        if topic == "cmd.move":
            rid = data.get("rid")
            vx = float(data.get("vx", 0.0))
            vy = float(data.get("vy", 0.0))
            yaw = float(data.get("yaw", data.get("az", 0.0)) or 0.0)

            dur = max(
                0.05,
                min(
                    float(data.get("duration", SAFE_MAX_DURATION) or SAFE_MAX_DURATION),
                    SAFE_MAX_DURATION,
                ),
            )
            publish_event(
                "rx_cmd.move",
                {"rid": rid, "vx": vx, "vy": vy, "yaw": yaw, "duration": dur},
            )

            now2 = time.time()

            # DROP_OLD_MS
            ts_in = data.get("ts")
            if ts_in:
                try:
                    age = (now2 - float(ts_in)) * 1000.0
                    if age > DROP_OLD_MS:
                        publish_event(
                            "skip_cmd.move",
                            {"rid": rid, "reason": "drop_old", "age_ms": round(age, 1)},
                        )
                        continue
                except Exception:
                    pass

            # Debounce
            if (now2 - _last_cmd_ts) < MIN_CMD_GAP:
                publish_event(
                    "skip_cmd.move",
                    {
                        "rid": rid,
                        "reason": "min_gap",
                        "gap_s": round(now2 - _last_cmd_ts, 3),
                    },
                )
                continue
            _last_cmd_ts = now2

            # PREEMPT
            if PREEMPT:
                _cancel_deadman()
                if ensure_xgo_open():
                    try:
                        xgo.stop()  # type: ignore[attr-defined]
                    except Exception as e:
                        print("[bridge] hw call error (preempt stop):", e, flush=True)

            ax, ay, aw = abs(vx), abs(vy), abs(yaw)
            moved = False

            if aw > 1e-4 and aw >= ax and aw >= ay:
                moved = True
                if yaw < 0:
                    do_turn_left(aw, dur)
                    publish_event(
                        "turn_left",
                        {"rid": rid, "step": _yaw_to_step(aw), "runtime": dur},
                    )
                else:
                    do_turn_right(aw, dur)
                    publish_event(
                        "turn_right",
                        {"rid": rid, "step": _yaw_to_step(aw), "runtime": dur},
                    )

            elif ax > 1e-4 and ax >= ay:
                moved = True
                if vx >= 0:
                    do_forward(ax, dur)
                    publish_event("forward", {"rid": rid, "v": ax, "runtime": dur})
                else:
                    do_backward(ax, dur)
                    publish_event("backward", {"rid": rid, "v": ax, "runtime": dur})

            elif ay > 1e-4:
                moved = True
                if vy >= 0:
                    do_strafe_right(ay, dur)
                    publish_event("right", {"rid": rid, "v": ay, "runtime": dur})
                else:
                    do_strafe_left(ay, dur)
                    publish_event("left", {"rid": rid, "v": ay, "runtime": dur})

            if moved:
                _last_motion_cmd_ts = now2

            _schedule_deadman(dur, rid)
            continue

        if topic == "cmd.stop":
            rid = data.get("rid")
            do_stop()
            publish_event("stop", {"rid": rid})
            _last_motion_cmd_ts = time.time()
            continue

        # Balance/stabilization control
        if topic == "cmd.balance":
            rid = data.get("rid")
            enabled = bool(data.get("enabled", False))
            print(f"[bridge] balance enabled={enabled}")
            if ensure_xgo_open():
                try:
                    # Try enable_balance first, fallback to set_stabilization
                    if hasattr(xgo, "enable_balance"):
                        xgo.enable_balance(enabled)  # type: ignore[attr-defined]
                    elif hasattr(xgo, "set_stabilization"):
                        xgo.set_stabilization(enabled)  # type: ignore[attr-defined]
                    elif hasattr(xgo, "imu"):
                        xgo.imu(1 if enabled else 0)  # type: ignore[attr-defined]
                    publish_event("balance", {"rid": rid, "enabled": enabled})
                except Exception as e:
                    print(f"[bridge] balance error: {e}", flush=True)
                    publish_event("balance_error", {"rid": rid, "error": str(e)})
            continue

        # Height/suspension control
        if topic == "cmd.height":
            rid = data.get("rid")
            try:
                height_cm = int(data.get("height", 0))
            except (ValueError, TypeError) as e:
                print(
                    f"[bridge] invalid height value: {data.get('height')}, error: {e}",
                    flush=True,
                )
                publish_event(
                    "height_error",
                    {"rid": rid, "error": f"invalid height: {data.get('height')}"},
                )
                continue
            # Clamp do bezpiecznego zakresu i mapuj do adaptera (70-115)
            # Input: 0-12 cm, Output: 70-115
            height_cm = max(0, min(12, height_cm))
            height_raw = int(70 + (height_cm / 12.0) * 45)
            print(f"[bridge] height cm={height_cm} raw={height_raw}")
            if ensure_xgo_open():
                try:
                    if hasattr(xgo, "set_height"):
                        xgo.set_height(height_raw)  # type: ignore[attr-defined]
                    elif hasattr(xgo, "rider_height"):
                        xgo.rider_height(height_raw)  # type: ignore[attr-defined]
                    publish_event(
                        "height",
                        {"rid": rid, "height_cm": height_cm, "height_raw": height_raw},
                    )
                except Exception as e:
                    print(f"[bridge] height error: {e}", flush=True)
                    publish_event("height_error", {"rid": rid, "error": str(e)})
            continue

        # STARE: zgodność wstecz
        rid = data.get("rid")
        spd = float(data.get("speed", 10.0))
        rt = max(0.05, min(float(data.get("runtime", 0.6)), SAFE_MAX_DURATION))

        if topic.endswith(".forward"):
            do_forward(spd if spd <= 1 else spd / max(1.0, TURN_STEP_MAX), rt)
            publish_event("forward", {"rid": rid, "v": spd, "runtime": rt})
            _schedule_deadman(rt, rid)
            _last_motion_cmd_ts = time.time()
        elif topic.endswith(".backward"):
            do_backward(spd if spd <= 1 else spd / max(1.0, TURN_STEP_MAX), rt)
            publish_event("backward", {"rid": rid, "v": spd, "runtime": rt})
            _schedule_deadman(rt, rid)
            _last_motion_cmd_ts = time.time()
        elif topic.endswith(".left"):
            do_strafe_left(spd if spd <= 1 else min(1.0, spd / 100.0), rt)
            publish_event("left", {"rid": rid, "v": spd, "runtime": rt})
            _schedule_deadman(rt, rid)
            _last_motion_cmd_ts = time.time()
        elif topic.endswith(".right"):
            do_strafe_right(spd if spd <= 1 else min(1.0, spd / 100.0), rt)
            publish_event("right", {"rid": rid, "v": spd, "runtime": rt})
            _schedule_deadman(rt, rid)
            _last_motion_cmd_ts = time.time()
        elif topic.endswith(".turn_left"):
            yawn = spd if spd <= 1 else min(1.0, spd / float(TURN_STEP_MAX))
            do_turn_left(abs(yawn), rt)
            publish_event(
                "turn_left",
                {"rid": rid, "step": _yaw_to_step(abs(yawn)), "runtime": rt},
            )
            _schedule_deadman(rt, rid)
            _last_motion_cmd_ts = time.time()
        elif topic.endswith(".turn_right"):
            yawn = spd if spd <= 1 else min(1.0, spd / float(TURN_STEP_MAX))
            do_turn_right(abs(yawn), rt)
            publish_event(
                "turn_right",
                {"rid": rid, "step": _yaw_to_step(abs(yawn)), "runtime": rt},
            )
            _schedule_deadman(rt, rid)
            _last_motion_cmd_ts = time.time()

print("[bridge] STOP", flush=True)
