# -*- coding: utf-8 -*-
"""
Rider-Pi – Motion Bridge (deadman auto-stop + debounce + RX echo + compat adapter)

- Słucha:
  * NOWE:  cmd.move {vx,vy,yaw|az,duration}, cmd.stop {}
  * STARE: cmd.motion.forward/backward/left/right/turn_left/turn_right/stop {speed,runtime}
- Mapuje na wywołania XGO; skręt bezpośrednio na vendorowe turnleft/turnright(step).
- Publikuje:
  * motion.bridge.event {event, detail}
  * devices.xgo {...}       ← telemetria dla dashboardu/API
      - yaw_raw  – surowy (skumulowany) kąt z IMU (może dryfować i >360°)
      - yaw      – heading 0–360° po stabilizacji (deadband + smoothing + freeze-idle)
      - yaw_rate_dps – wyliczona prędkość kątowa (deg/s)
      - yaw_src  – "gyro_stabilized" albo "heading_native", jeśli dostępne

ENV:
- BUS_PUB_PORT=5555, BUS_SUB_PORT=5556
- DRY_RUN=1 (domyślnie) → nie dotyka sprzętu
- BRIDGE_READONLY=1       → publikuj telemetrię, ale bez ruchów
- XGO_LAZY_OPEN=1         → port otwierany leniwie (przy pierwszym odczycie)
- XGO_PORT=/dev/ttyAMA0
- BRIDGE_RATE_HZ=2        → jak często publikować telemetrię
- SPEED_LINEAR=12         (skala dla f/b/strafe)
- SAFE_MAX_DURATION=0.6   (twardy limit czasu pojedynczego ruchu, sek.)
- MIN_CMD_GAP=0.10        (min. odstęp między ruchami, sek. – anty „double tap”)
- TURN_STEP_MIN=20, TURN_STEP_MAX=70  (zakres kroku dla turnleft/turnright)
- YAW_DEADBAND_DPS=0.8    ← dryf <0.8°/s uznaj za szum (nie przesuwaj headingu)
- YAW_SMOOTH_ALPHA=0.2    ← wygładzenie EMA (0–1), 0 = brak, 1 = brak wygładzania
- YAW_FREEZE_WHEN_IDLE_S=2.0  ← po tylu sekundach bez ruchu zamrażamy heading
- YAW_IDLE_MAX_DPS=8.0        ← ale tylko gdy |yaw_rate| poniżej tego progu
"""

import os, time, json, signal, threading
from threading import Timer
from typing import Optional, Any, Callable, List, Tuple
import zmq  # type: ignore

# --- ENV / parametry ---
BUS_PUB_PORT      = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT      = int(os.getenv("BUS_SUB_PORT", "5556"))
DRY_RUN           = (os.getenv("DRY_RUN", "1") == "1")
BRIDGE_READONLY   = (os.getenv("BRIDGE_READONLY", "1") == "1")
XGO_LAZY_OPEN     = (os.getenv("XGO_LAZY_OPEN", "1") == "1")
XGO_PORT          = os.getenv("XGO_PORT", "/dev/ttyAMA0")
BRIDGE_RATE_HZ    = float(os.getenv("BRIDGE_RATE_HZ", "2"))
BRIDGE_RATE_HZ    = max(0.1, min(20.0, BRIDGE_RATE_HZ))

SPEED_LINEAR      = float(os.getenv("SPEED_LINEAR", "12"))
SAFE_MAX_DURATION = float(os.getenv("SAFE_MAX_DURATION", "0.6"))
MIN_CMD_GAP       = float(os.getenv("MIN_CMD_GAP", "0.10"))

TURN_STEP_MIN     = int(os.getenv("TURN_STEP_MIN", "20"))
TURN_STEP_MAX     = int(os.getenv("TURN_STEP_MAX", "70"))

# Stabilizacja yaw
YAW_DEADBAND_DPS  = float(os.getenv("YAW_DEADBAND_DPS", "0.8"))
YAW_SMOOTH_ALPHA  = float(os.getenv("YAW_SMOOTH_ALPHA", "0.2"))
YAW_SMOOTH_ALPHA  = max(0.0, min(1.0, YAW_SMOOTH_ALPHA))
YAW_FREEZE_WHEN_IDLE_S = float(os.getenv("YAW_FREEZE_WHEN_IDLE_S", "2.0"))
YAW_IDLE_MAX_DPS       = float(os.getenv("YAW_IDLE_MAX_DPS", "8.0"))

MOVES_ALLOWED = (not DRY_RUN) and (not BRIDGE_READONLY)

# --- heading helpery ---
def _norm360(deg: Optional[float]) -> Optional[float]:
    if deg is None: return None
    try:
        x = float(deg) % 360.0
        return x if x >= 0.0 else x + 360.0
    except Exception:
        return None

def _angle_diff_deg(a: float, b: float) -> float:
    """różnica kierunków a-b w stopniach, z zawinięciem do (-180,180]"""
    d = (a - b + 180.0) % 360.0 - 180.0
    return d

# Stan filtra yaw
_yaw_state = {
    "ts": None,             # type: Optional[float]
    "yaw_raw": None,        # type: Optional[float]
    "yaw_stable": None,     # type: Optional[float]  # 0..360
    "src": "gyro_stabilized",
}
_last_motion_cmd_ts = 0.0   # znacznik ostatniej komendy ruchu (do freeze-idle)

def _stabilize_yaw(yaw_raw: Optional[float], ts: float, freeze: bool = False) -> Tuple[Optional[float], Optional[float], str]:
    """
    Z wejściowego yaw_raw (skumulowany gyro) policz:
      - yaw_rate_dps: (yaw_raw_now - yaw_raw_prev)/dt (deg/s)
      - yaw_stable: heading 0..360 z deadbandem i EMA
      - jeśli freeze=True i mamy poprzedni heading → nie aktualizuj headingu
    """
    global _yaw_state
    if yaw_raw is None:
        _yaw_state["ts"] = ts
        return None, None, _yaw_state["src"]

    prev_ts   = _yaw_state["ts"]
    prev_raw  = _yaw_state["yaw_raw"]
    prev_stab = _yaw_state["yaw_stable"]

    if prev_ts is not None and prev_raw is not None:
        dt = max(1e-6, ts - float(prev_ts))
        yaw_rate = (float(yaw_raw) - float(prev_raw)) / dt  # deg/s
    else:
        yaw_rate = 0.0

    base_heading = _norm360(yaw_raw)

    if prev_stab is None or base_heading is None:
        stab = base_heading
    else:
        if freeze:
            stab = prev_stab
        elif abs(yaw_rate or 0.0) < YAW_DEADBAND_DPS:
            stab = prev_stab
        else:
            step = _angle_diff_deg(base_heading, prev_stab)
            raw_next = (prev_stab + step) % 360.0
            if YAW_SMOOTH_ALPHA <= 0.0:
                stab = raw_next
            elif YAW_SMOOTH_ALPHA >= 1.0:
                stab = base_heading
            else:
                stab = (1.0 - YAW_SMOOTH_ALPHA) * prev_stab + YAW_SMOOTH_ALPHA * raw_next
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

xgo = None  # będzie instancją po ensure_xgo_open()

def ensure_xgo_open() -> Optional[Any]:
    """Otwórz połączenie z XGO, jeśli jeszcze nie istnieje."""
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

def _list_hw_methods() -> List[str]:
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
sub.connect(f"tcp://127.0.0.1:{BUS_SUB_PORT}")
for t in [
    "cmd.motion.forward","cmd.motion.backward","cmd.motion.left","cmd.motion.right",
    "cmd.motion.turn_left","cmd.motion.turn_right","cmd.motion.stop","cmd.motion.demo",
    "cmd.move","cmd.stop"
]:
    sub.setsockopt_string(zmq.SUBSCRIBE, t)

# anti slow-joiner – daj brokerowi czas na ustanowienie subskrypcji
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
def _get_val(names: List[str], post: Optional[Callable[[Any], Any]] = None) -> Any:
    """Wywołaj pierwszą dostępną metodę z listy; bezpiecznie przechwyć błędy."""
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
    # Preferowana: natywny heading/compass, jeśli istnieje
    dev = xgo or ensure_xgo_open()
    if dev:
        for m in ("read_heading", "rider_read_heading", "heading", "read_yaw_deg360"):
            fn = getattr(dev, m, None)
            if callable(fn):
                try:
                    h = float(fn())
                    return ( _get_val(["read_roll","rider_read_roll"], float),
                             _get_val(["read_pitch","rider_read_pitch"], float),
                             float(h), "heading_native" )
                except Exception:
                    pass

    # Standardowe trio gyro euler
    for trio in [
        ("read_roll","read_pitch","read_yaw"),
        ("rider_read_roll","rider_read_pitch","rider_read_yaw"),
    ]:
        dev = xgo or ensure_xgo_open()
        if not dev:
            return (None, None, None, "gyro_stabilized")
        try:
            r = getattr(dev, trio[0])()
            p = getattr(dev, trio[1])()
            y = getattr(dev, trio[2])()
            return (float(r), float(p), float(y), "gyro_stabilized")
        except Exception:
            continue
    # Pakietowa IMU
    v = _get_val(["read_imu", "read_imu_int16", "rider_read_imu_int16"])
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        try:
            return (float(v[0]), float(v[1]), float(v[2]), "gyro_stabilized")
        except Exception:
            return (None, None, None, "gyro_stabilized")
    return (None, None, None, "gyro_stabilized")

def read_xgo_telemetry() -> dict:
    """Zbierz prostą telemetrię z XGO (bez pieczenia CPU)."""
    dev = xgo if xgo is not None else (ensure_xgo_open() if not XGO_LAZY_OPEN else xgo)

    batt = _get_val(["rider_read_battery", "read_battery"])
    fw   = _get_val(["rider_read_firmware", "read_firmware", "version"])
    roll, pitch, yaw_raw, yaw_src = _read_attitude()

    ts = time.time()

    # jeśli mamy heading natywny – używamy go bez stabilizacji (tylko norm360)
    if yaw_src == "heading_native":
        yaw_norm = _norm360(yaw_raw)
        yaw_rate = None
        yaw_out  = yaw_norm
        src_out  = "heading_native"
    else:
        # policz przewidywany yaw_rate (bez modyfikacji stanu) do warunku freeze
        prev_ts  = _yaw_state["ts"]
        prev_raw = _yaw_state["yaw_raw"]
        if prev_ts is not None and prev_raw is not None and yaw_raw is not None:
            dt_est = max(1e-6, ts - float(prev_ts))
            yaw_rate_est = (float(yaw_raw) - float(prev_raw)) / dt_est
        else:
            yaw_rate_est = 0.0

        idle_for = ts - (_last_motion_cmd_ts or 0.0)
        freeze = (idle_for >= YAW_FREEZE_WHEN_IDLE_S) and (abs(yaw_rate_est) < YAW_IDLE_MAX_DPS)

        yaw_stable, yaw_rate, _ = _stabilize_yaw(yaw_raw, ts, freeze=freeze)
        yaw_out = yaw_stable
        src_out = "gyro_stabilized"

    telem = {
        "present": bool(xgo is not None),
        "imu_ok": (roll is not None and pitch is not None and yaw_raw is not None),
        "pose": None,
        "battery_pct": float(batt) if batt is not None else None,
        "roll": roll,
        "pitch": pitch,
        "yaw_raw": yaw_raw,
        "yaw": yaw_out,            # heading 0..360 po stabilizacji / lub natywny
        "yaw_rate_dps": yaw_rate,
        "yaw_src": src_out,
        "fw": fw,
        "ts": ts,
    }
    return telem

_last_telem_print = 0.0
def publish_devices_xgo(payload: dict):
    global _last_telem_print
    _pub_json("devices.xgo", payload)
    # kontrolny log nie częściej niż co 2 s
    now = time.time()
    if now - _last_telem_print >= 2.0:
        print("[bridge] devices.xgo ->", payload, flush=True)
        _last_telem_print = now

# --- Deadman (autostop po czasie) ---
_deadman_lock = threading.Lock()
_deadman_timer: Optional[Timer] = None

def _cancel_deadman():
    global _deadman_timer
    with _deadman_lock:
        if _deadman_timer is not None:
            try: _deadman_timer.cancel()
            except Exception: pass
        _deadman_timer = None

def _schedule_deadman(duration_s: float):
    """Zawsze planujemy autostop po czasie (niezależnie od FW)."""
    global _deadman_timer
    d = max(0.05, min(float(duration_s or 0.0), SAFE_MAX_DURATION))
    _cancel_deadman()
    def _fire():
        try:
            if MOVES_ALLOWED and ensure_xgo_open():
                try:
                    xgo.stop()  # type: ignore[attr-defined]
                except Exception as e:
                    print("[bridge] hw call error:", e, flush=True)
            publish_event("auto_stop", {"after_s": d})
        except Exception:
            pass
    t = Timer(d, _fire)
    t.daemon = True
    with _deadman_lock:
        _deadman_timer = t
    t.start()

# --- Helpery wywołań HW ---
def _set_speed_if_possible(speed: float):
    dev = ensure_xgo_open()
    if not dev: return
    for m in ("set_move_speed", "set_speed", "speed", "setSpeed", "setSpd"):
        fn = getattr(dev, m, None)
        if callable(fn):
            try:
                fn(float(speed)); return
            except Exception:
                pass

def _try_call(fn, *args) -> bool:
    try:
        fn(*args); return True
    except TypeError:
        return False
    except Exception as e:
        print("[bridge] hw call error:", e, flush=True)
        return True  # błąd runtime → nie próbuj dalej

def _call_move(method_name: str, *args):
    """Wywołaj metodę bez kombinowania z podpisami – podajemy to, co vendor oczekuje."""
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
    try: v = float(v)
    except Exception: return 0.0
    return 0.0 if v < 0 else 1.0 if v > 1 else v

def _yaw_to_step(yaw_abs_01: float) -> int:
    """Mapuje |yaw| z [0..1] na krok vendorowy [TURN_STEP_MIN..TURN_STEP_MAX]."""
    s = _clamp01(yaw_abs_01)
    step = int(round(TURN_STEP_MIN + s * (TURN_STEP_MAX - TURN_STEP_MIN)))
    return max(TURN_STEP_MIN, min(TURN_STEP_MAX, step))

# --- Akcje wysokiego poziomu ---
def do_forward(speed_norm, runtime):
    spd = SPEED_LINEAR * _clamp01(abs(speed_norm))
    print(f"[bridge] forward v={spd:.2f} t={runtime:.2f}")
    if MOVES_ALLOWED:
        dev = ensure_xgo_open()
        if dev and hasattr(dev, "forward"):
            if not _try_call(getattr(dev,"forward"), spd):
                if not _try_call(getattr(dev,"forward"), runtime):
                    _try_call(getattr(dev,"forward"), spd, runtime)

def do_backward(speed_norm, runtime):
    spd = SPEED_LINEAR * _clamp01(abs(speed_norm))
    print(f"[bridge] backward v={spd:.2f} t={runtime:.2f}")
    if MOVES_ALLOWED:
        dev = ensure_xgo_open()
        if dev:
            meth = "back" if hasattr(dev, "back") else ("backward" if hasattr(dev, "backward") else None)
            if meth:
                if not _try_call(getattr(dev,meth), spd):
                    if not _try_call(getattr(dev,meth), runtime):
                        _try_call(getattr(dev,meth), spd, runtime)

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
    if MOVES_ALLOWED and ensure_xgo_open():
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

# Jeśli nie leniwie – spróbuj otworzyć port już teraz (żeby od razu mieć present=True)
if not XGO_LAZY_OPEN:
    ensure_xgo_open()

print(
    "[bridge] START "
    f"(PUB:{BUS_PUB_PORT} SUB:{BUS_SUB_PORT} "
    f"DRY_RUN={bool(DRY_RUN)} READONLY={bool(BRIDGE_READONLY)} "
    f"MOVES_ALLOWED={bool(MOVES_ALLOWED)} LAZY={bool(XGO_LAZY_OPEN)} "
    f"RATE_HZ={BRIDGE_RATE_HZ} PORT={XGO_PORT} "
    f"SAFE_MAX={SAFE_MAX_DURATION}s MIN_GAP={MIN_CMD_GAP}s "
    f"YAW_DEADBAND_DPS={YAW_DEADBAND_DPS} YAW_SMOOTH_ALPHA={YAW_SMOOTH_ALPHA} "
    f"FREEZE_IDLE_S={YAW_FREEZE_WHEN_IDLE_S} IDLE_MAX_DPS={YAW_IDLE_MAX_DPS})",
    flush=True
)
print("[bridge] hw methods:", ", ".join(_list_hw_methods()), flush=True)
publish_event("ready", {"ts": time.time()})

_last_cmd_ts = 0.0       # debounce
_next_telem_ts = 0.0     # harmonogram telemetrii

# --- pętla główna ---
tick_dt = 0.01
while _running:
    now = time.time()

    # Telemetria – zgodnie z BRIDGE_RATE_HZ
    if now >= _next_telem_ts:
        publish_devices_xgo(read_xgo_telemetry())
        _next_telem_ts = now + (1.0 / BRIDGE_RATE_HZ)

    # Odbiór komend
    try:
        msg = sub.recv_string(flags=zmq.NOBLOCK)
    except zmq.Again:
        time.sleep(tick_dt); continue
    except Exception as e:
        print("[bridge] recv error:", e, flush=True)
        time.sleep(0.1); continue

    try:
        topic, payload = msg.split(" ", 1)
    except ValueError:
        topic, payload = msg, "{}"

    try:
        data = json.loads(payload) if payload else {}
    except Exception:
        data = {}

    # NOWE: REST cmd.move / cmd.stop
    if topic == "cmd.move":
        vx  = float(data.get("vx", 0.0))
        vy  = float(data.get("vy", 0.0))
        yaw = data.get("yaw", None)
        if yaw is None:
            yaw = data.get("az", 0.0)
        yaw = float(yaw or 0.0)

        dur = float(data.get("duration", SAFE_MAX_DURATION) or SAFE_MAX_DURATION)
        dur = max(0.05, min(dur, SAFE_MAX_DURATION))

        publish_event("rx_cmd.move", {"vx": vx, "vy": vy, "yaw": yaw, "duration": dur})

        now2 = time.time()
        if (now2 - _last_cmd_ts) < MIN_CMD_GAP:
            publish_event("skip_cmd.move", {"reason":"min_gap", "gap_s": round(now2 - _last_cmd_ts, 3)})
            continue
        _last_cmd_ts = now2

        ax, ay, aw = abs(vx), abs(vy), abs(yaw)
        moved = False

        # Priorytet: skręt (aw) > jazda liniowa (ax) > strafe (ay)
        if aw > 1e-4 and aw >= ax and aw >= ay:
            moved = True
            if yaw < 0:
                do_turn_left(aw, dur);  publish_event("turn_left",  {"step": _yaw_to_step(aw), "runtime": dur})
            else:
                do_turn_right(aw, dur); publish_event("turn_right", {"step": _yaw_to_step(aw), "runtime": dur})

        elif ax > 1e-4 and ax >= ay:
            moved = True
            if vx >= 0:
                do_forward(ax, dur);  publish_event("forward",  {"v": ax, "runtime": dur})
            else:
                do_backward(ax, dur); publish_event("backward", {"v": ax, "runtime": dur})

        elif ay > 1e-4:
            moved = True
            if vy >= 0:
                do_strafe_right(ay, dur); publish_event("right", {"v": ay, "runtime": dur})
            else:
                do_strafe_left(ay, dur);  publish_event("left",  {"v": ay, "runtime": dur})

        if moved:
            _last_motion_cmd_ts = now2

        _schedule_deadman(dur)
        continue

    if topic == "cmd.stop":
        do_stop(); publish_event("stop", {})
        _last_motion_cmd_ts = time.time()  # początek „idle” od STOP
        continue

    # STARE: zgodność wstecz (cmd.motion.*)
    spd = float(data.get("speed", 10.0))
    rt  = max(0.05, min(float(data.get("runtime", 0.6)), SAFE_MAX_DURATION))

    if   topic.endswith(".forward"):
        do_forward(spd if spd<=1 else spd/max(1.0, TURN_STEP_MAX), rt); publish_event("forward", {"v": spd, "runtime": rt}); _schedule_deadman(rt); _last_motion_cmd_ts = time.time()
    elif topic.endswith(".backward"):
        do_backward(spd if spd<=1 else spd/max(1.0, TURN_STEP_MAX), rt); publish_event("backward", {"v": spd, "runtime": rt}); _schedule_deadman(rt); _last_motion_cmd_ts = time.time()
    elif topic.endswith(".left"):
        do_strafe_left(spd if spd<=1 else min(1.0, spd/100.0), rt);  publish_event("left", {"v": spd, "runtime": rt}); _schedule_deadman(rt); _last_motion_cmd_ts = time.time()
    elif topic.endswith(".right"):
        do_strafe_right(spd if spd<=1 else min(1.0, spd/100.0), rt); publish_event("right", {"v": spd, "runtime": rt}); _schedule_deadman(rt); _last_motion_cmd_ts = time.time()
    elif topic.endswith(".turn_left"):
        yawn = spd if spd<=1 else min(1.0, spd/float(TURN_STEP_MAX))
        do_turn_left(abs(yawn), rt);  publish_event("turn_left", {"step": _yaw_to_step(abs(yawn)), "runtime": rt}); _schedule_deadman(rt); _last_motion_cmd_ts = time.time()
    elif topic.endswith(".turn_right"):
        yawn = spd if spd<=1 else min(1.0, spd/float(TURN_STEP_MAX))
        do_turn_right(abs(yawn), rt); publish_event("turn_right", {"step": _yaw_to_step(abs(yawn)), "runtime": rt}); _schedule_deadman(rt); _last_motion_cmd_ts = time.time()
    elif topic.endswith(".stop"):
        do_stop(); publish_event("stop", {}); _last_motion_cmd_ts = time.time()

print("[bridge] STOP", flush=True)
