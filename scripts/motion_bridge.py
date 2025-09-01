# -*- coding: utf-8 -*-
"""
Rider-Pi – Motion Bridge (deadman auto-stop + debounce + RX echo + compat adapter)

- Słucha:
  * NOWE:  cmd.move {vx,vy,yaw|az,duration}, cmd.stop {}
  * STARE: cmd.motion.forward/backward/left/right/turn_left/turn_right/stop {speed,runtime}
- Mapuje na wywołania XGO; skręt bezpośrednio na vendorowe turnleft/turnright(step).
- Publikuje: motion.bridge.event {event, detail}

ENV:
- BUS_PUB_PORT=5555, BUS_SUB_PORT=5556
- DRY_RUN=1 (domyślnie) → nie dotyka sprzętu
- SPEED_LINEAR=12                  (skala dla f/b/strafe)
- SAFE_MAX_DURATION=0.6            (twardy limit czasu pojedynczego ruchu, sek.)
- MIN_CMD_GAP=0.10                 (min. odstęp między ruchami, sek. – anty „double tap”)
- TURN_STEP_MIN=20, TURN_STEP_MAX=70  (zakres kroku dla turnleft/turnright)
"""

import os, time, json, signal, threading
from threading import Timer
from typing import Optional
import zmq  # type: ignore

# --- ENV / parametry ---
BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
DRY_RUN      = (os.getenv("DRY_RUN", "1") == "1")

SPEED_LINEAR = float(os.getenv("SPEED_LINEAR", "12"))
SAFE_MAX_DURATION = float(os.getenv("SAFE_MAX_DURATION", "0.6"))
MIN_CMD_GAP  = float(os.getenv("MIN_CMD_GAP", "0.10"))

TURN_STEP_MIN = int(os.getenv("TURN_STEP_MIN", "20"))
TURN_STEP_MAX = int(os.getenv("TURN_STEP_MAX", "70"))

# --- Opcjonalny sterownik XGO ---
xgo = None
try:
    from xgolib import XGO  # type: ignore
    xgo = XGO(port="/dev/ttyAMA0")
except Exception:
    xgo = None

def _list_hw_methods():
    if not xgo: return []
    return [m for m in dir(xgo) if not m.startswith("_")]

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

def publish_event(name: str, detail: dict):
    try:
        payload = {"ts": time.time(), "event": name, "detail": (detail or {})}
        pub.send_string(f"motion.bridge.event {json.dumps(payload, ensure_ascii=False)}")
    except Exception:
        pass
    print(f"[bridge] {name}: {detail}", flush=True)

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
            if not DRY_RUN and xgo:
                try:
                    xgo.stop()
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
    if not xgo: return
    for m in ("set_move_speed", "set_speed", "speed", "setSpeed", "setSpd"):
        fn = getattr(xgo, m, None)
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
    if DRY_RUN or not xgo:
        return
    fn = getattr(xgo, method_name, None)
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
    # speed_norm: 0..1 → przeskaluj do SPEED_LINEAR
    spd = SPEED_LINEAR * _clamp01(abs(speed_norm))
    print(f"[bridge] forward v={spd:.2f} t={runtime:.2f}")
    # w niektórych FW: forward(step) lub forward(step, t) lub forward(t)
    # Spróbujemy najpierw (step), potem (t), potem (step,t)
    if not DRY_RUN and xgo:
        if hasattr(xgo, "forward"):
            if not _try_call(getattr(xgo,"forward"), spd):
                if not _try_call(getattr(xgo,"forward"), runtime):
                    _try_call(getattr(xgo,"forward"), spd, runtime)

def do_backward(speed_norm, runtime):
    spd = SPEED_LINEAR * _clamp01(abs(speed_norm))
    print(f"[bridge] backward v={spd:.2f} t={runtime:.2f}")
    if not DRY_RUN and xgo:
        meth = "back" if hasattr(xgo, "back") else ("backward" if hasattr(xgo, "backward") else None)
        if meth:
            if not _try_call(getattr(xgo,meth), spd):
                if not _try_call(getattr(xgo,meth), runtime):
                    _try_call(getattr(xgo,meth), spd, runtime)

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
    if not DRY_RUN and xgo:
        try:
            xgo.stop()
        except Exception as e:
            print("[bridge] hw call error:", e, flush=True)

# --- sygnały, start ---
_running = True
def _sigterm(*_):
    global _running
    _running = False
signal.signal(signal.SIGINT, _sigterm)
signal.signal(signal.SIGTERM, _sigterm)

print(f"[bridge] START (PUB:{BUS_PUB_PORT} SUB:{BUS_SUB_PORT} DRY_RUN={bool(DRY_RUN)} SAFE_MAX_DURATION={SAFE_MAX_DURATION} MIN_CMD_GAP={MIN_CMD_GAP})", flush=True)
print("[bridge] hw methods:", ", ".join(_list_hw_methods()), flush=True)
publish_event("ready", {"ts": time.time()})

_last_cmd_ts = 0.0  # debounce

# --- pętla główna ---
while _running:
    try:
        msg = sub.recv_string(flags=zmq.NOBLOCK)
    except zmq.Again:
        time.sleep(0.01); continue
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
        # weź 'yaw' albo fallback 'az'
        yaw = data.get("yaw", None)
        if yaw is None:
            yaw = data.get("az", 0.0)
        yaw = float(yaw or 0.0)

        dur = float(data.get("duration", SAFE_MAX_DURATION) or SAFE_MAX_DURATION)
        dur = max(0.05, min(dur, SAFE_MAX_DURATION))

        publish_event("rx_cmd.move", {"vx": vx, "vy": vy, "yaw": yaw, "duration": dur})

        now = time.time()
        if (now - _last_cmd_ts) < MIN_CMD_GAP:
            publish_event("skip_cmd.move", {"reason":"min_gap", "gap_s": round(now - _last_cmd_ts, 3)})
            continue
        _last_cmd_ts = now

        ax, ay, aw = abs(vx), abs(vy), abs(yaw)

        # Priorytet: skręt (aw) > jazda liniowa (ax) > strafe (ay)
        if aw > 1e-4 and aw >= ax and aw >= ay:
            if yaw < 0:
                do_turn_left(aw, dur);  publish_event("turn_left",  {"step": _yaw_to_step(aw), "runtime": dur})
            else:
                do_turn_right(aw, dur); publish_event("turn_right", {"step": _yaw_to_step(aw), "runtime": dur})

        elif ax > 1e-4 and ax >= ay:
            if vx >= 0:
                do_forward(ax, dur);  publish_event("forward",  {"v": ax, "runtime": dur})
            else:
                do_backward(ax, dur); publish_event("backward", {"v": ax, "runtime": dur})

        elif ay > 1e-4:
            if vy >= 0:
                do_strafe_right(ay, dur); publish_event("right", {"v": ay, "runtime": dur})
            else:
                do_strafe_left(ay, dur);  publish_event("left",  {"v": ay, "runtime": dur})

        _schedule_deadman(dur)
        continue

    if topic == "cmd.stop":
        do_stop(); publish_event("stop", {})
        continue

    # STARE: zgodność wstecz (cmd.motion.*)
    spd = float(data.get("speed", 10.0))
    rt  = max(0.05, min(float(data.get("runtime", 0.6)), SAFE_MAX_DURATION))

    if   topic.endswith(".forward"):
        do_forward(spd if spd<=1 else spd/ max(1.0, TURN_STEP_MAX), rt); publish_event("forward", {"v": spd, "runtime": rt}); _schedule_deadman(rt)
    elif topic.endswith(".backward"):
        do_backward(spd if spd<=1 else spd/ max(1.0, TURN_STEP_MAX), rt); publish_event("backward", {"v": spd, "runtime": rt}); _schedule_deadman(rt)
    elif topic.endswith(".left"):
        do_strafe_left(spd if spd<=1 else min(1.0, spd/100.0), rt);  publish_event("left", {"v": spd, "runtime": rt}); _schedule_deadman(rt)
    elif topic.endswith(".right"):
        do_strafe_right(spd if spd<=1 else min(1.0, spd/100.0), rt); publish_event("right", {"v": spd, "runtime": rt}); _schedule_deadman(rt)
    elif topic.endswith(".turn_left"):
        # z liczb "vendorowych" zrób krok bezpieczny
        yawn = spd if spd<=1 else min(1.0, spd/float(TURN_STEP_MAX))
        do_turn_left(abs(yawn), rt);  publish_event("turn_left", {"step": _yaw_to_step(abs(yawn)), "runtime": rt}); _schedule_deadman(rt)
    elif topic.endswith(".turn_right"):
        yawn = spd if spd<=1 else min(1.0, spd/float(TURN_STEP_MAX))
        do_turn_right(abs(yawn), rt); publish_event("turn_right", {"step": _yaw_to_step(abs(yawn)), "runtime": rt}); _schedule_deadman(rt)
    elif topic.endswith(".stop"):
        do_stop(); publish_event("stop", {})

print("[bridge] STOP", flush=True)

