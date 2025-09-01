# -*- coding: utf-8 -*-
"""
Rider-Pi – Motion Bridge (deadman auto-stop + debounce + RX echo + compat adapter)

- Słucha:
  * NOWE:  cmd.move {vx,vy,yaw,duration}, cmd.stop {}
  * STARE: cmd.motion.forward/backward/left/right/turn_left/turn_right/stop {speed,runtime}
- Mapuje na wywołania XGO (różne sygnatury obsługiwane) lub DRY RUN.
- Pivot skrętu: preferuj 'translation' (jeśli wspierane), potem aliasy turn*/rider_turn itp.
- Publikuje: motion.bridge.event {event, detail}

ENV:
- BUS_PUB_PORT=5555, BUS_SUB_PORT=5556
- DRY_RUN=1 (domyślnie) → nie dotyka sprzętu
- SPEED_LINEAR=12, SPEED_TURN=20
- SAFE_MAX_DURATION=0.6  (twardy limit czasu pojedynczego ruchu, sek.)
- MIN_CMD_GAP=0.10       (min. odstęp między ruchami, sek. – anty „double tap”)
- TURN_RIGHT_ALIASES, TURN_LEFT_ALIASES – lista nazw metod dla skrętu (priorytet wg kolejności)
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
SPEED_TURN   = float(os.getenv("SPEED_TURN",   "20"))
SAFE_MAX_DURATION = float(os.getenv("SAFE_MAX_DURATION", "0.6"))
MIN_CMD_GAP  = float(os.getenv("MIN_CMD_GAP", "0.10"))

# --- aliasy metod skrętu z ENV (pierwsze na liście mają priorytet) ---
TURN_RIGHT_ALIASES = [s.strip() for s in os.getenv(
    "TURN_RIGHT_ALIASES",
    "turn,turn_by,turnright,rider_turn,turn_right,clockwise,cw,rotate_right"
).split(",") if s.strip()]

TURN_LEFT_ALIASES  = [s.strip() for s in os.getenv(
    "TURN_LEFT_ALIASES",
    "turn,turn_by,turnleft,rider_turn,turn_left,counterclockwise,ccw,rotate_left"
).split(",") if s.strip()]

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

# --- Adapter wywołań (różne sygnatury XGO) ---
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

def _call_move(method_name: str, speed: float, runtime: float):
    """
    Wywołaj metodę ruchu z różnymi sygnaturami.
    Ważne: NAJPIERW próbujemy wariantu ze speed, bo forward/turn* zwykle mają tylko speed.
    """
    if DRY_RUN or not xgo:
        return
    fn = getattr(xgo, method_name, None)
    if not callable(fn):
        print(f"[bridge] hw call missing method: {method_name}", flush=True)
        return

    # 1) (speed, runtime)
    if _try_call(fn, speed, runtime):   return

    # 2) set_speed + (runtime)
    _set_speed_if_possible(speed)
    if _try_call(fn, runtime):          return

    # 3) (speed)  ← PRIORYTET
    if _try_call(fn, speed):            return

    # 4) ()
    if _try_call(fn):                   return

    print(f"[bridge] hw call: no compatible signature for {method_name}", flush=True)

def _try_translation_pivot(az: float, runtime: float) -> bool:
    """
    Spróbuj wykonać pivot poprzez 'translation' (różne FW mają różne podpisy).
    Zwraca True jeśli udało się wywołać jakąś wersję.
    """
    if DRY_RUN or not xgo: return False
    fn = getattr(xgo, "translation", None)
    if not callable(fn): return False

    # az w [0..1]
    az = max(0.0, min(1.0, float(az)))

    # kolejno testujemy popularne warianty:
    # - translation('z', az)
    # - translation(az)
    # - translation(0.0, az)  (spotykane w jednym z forków)
    tries = [
        ("translation('z', az)",   lambda: fn('z', az)),
        ("translation(az)",        lambda: fn(az)),
        ("translation(0.0, az)",   lambda: fn(0.0, az)),
    ]
    for label, call in tries:
        try:
            call()
            print(f"[bridge] turn_right via translation az={az:.2f} t={runtime:.2f}")
            publish_event("turn_method_used", {"dir":"right", "method": "translation"})
            return True
        except TypeError:
            continue
        except Exception as e:
            print("[bridge] hw call error:", e, flush=True)
            return True  # błąd runtime → przerywamy
    return False

def _pick_turn_method(direction: str) -> Optional[str]:
    """Wybierz najlepszą metodę skrętu zgodnie z ENV i tym, co faktycznie jest w xgo."""
    cands = (TURN_RIGHT_ALIASES if direction == "right" else TURN_LEFT_ALIASES) + [
        # awaryjne ogólne nazwy – różne forki mają różnie:
        "turnright" if direction == "right" else "turnleft",
        "turn", "turn_by", "rider_turn", "turn_to",
    ]
    if not xgo: return None
    for m in cands:
        fn = getattr(xgo, m, None)
        if callable(fn):
            return m
    return None

# --- Akcje wysokiego poziomu ---
def do_forward(speed, runtime):
    print(f"[bridge] forward speed={speed:.2f} t={runtime:.2f}")
    _call_move("forward", speed, runtime)

def do_backward(speed, runtime):
    print(f"[bridge] backward speed={speed:.2f} t={runtime:.2f}")
    # w jednych FW nazywa się 'back', w innych 'backward'
    meth = "back" if hasattr(xgo, "back") else "backward"
    _call_move(meth, speed, runtime)

def do_left(speed, runtime):
    print(f"[bridge] left speed={speed:.2f} t={runtime:.2f}")
    _call_move("left", speed, runtime)

def do_right(speed, runtime):
    print(f"[bridge] right speed={speed:.2f} t={runtime:.2f}")
    _call_move("right", speed, runtime)

def do_turn_left(speed, runtime):
    # najpierw spróbuj pivotu przez translation (lewo: az>0 też obraca, kierunek zależy od FW)
    if _try_translation_pivot(az=min(1.0, abs(speed)/max(1.0, SPEED_TURN)), runtime=runtime):
        return
    m = _pick_turn_method("left")
    print(f"[bridge] turn_left speed={speed:.2f} t={runtime:.2f} method={m}")
    if not m:
        print("[bridge] hw call missing turn method (left)", flush=True)
        return
    publish_event("turn_method_used", {"dir":"left", "method": m})
    _call_move(m, speed, runtime)

def do_turn_right(speed, runtime):
    # najpierw spróbuj pivotu przez translation (prawo)
    if _try_translation_pivot(az=min(1.0, abs(speed)/max(1.0, SPEED_TURN)), runtime=runtime):
        return
    m = _pick_turn_method("right")
    print(f"[bridge] turn_right speed={speed:.2f} t={runtime:.2f} method={m}")
    if not m:
        print("[bridge] hw call missing turn method (right)", flush=True)
        return
    publish_event("turn_method_used", {"dir":"right", "method": m})
    _call_move(m, speed, runtime)

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
        yaw = float(data.get("yaw", 0.0))
        dur = float(data.get("duration", 0.6) or 0.6)
        dur = max(0.05, min(dur, SAFE_MAX_DURATION))

        publish_event("rx_cmd.move", {"vx": vx, "vy": vy, "yaw": yaw, "duration": dur})

        now = time.time()
        if (now - _last_cmd_ts) < MIN_CMD_GAP:
            publish_event("skip_cmd.move", {"reason":"min_gap", "gap_s": round(now - _last_cmd_ts, 3)})
            continue
        _last_cmd_ts = now

        ax, ay, aw = abs(vx), abs(vy), abs(yaw)
        if aw >= ax and aw >= ay and aw > 0:
            # skręt – przelicz na prędkość kątową
            if yaw >= 0:
                do_turn_right(SPEED_TURN*aw, dur); publish_event("turn_right", {"speed": SPEED_TURN*aw, "runtime": dur})
            else:
                do_turn_left (SPEED_TURN*aw, dur); publish_event("turn_left",  {"speed": SPEED_TURN*aw, "runtime": dur})
        elif ax >= ay and ax > 0:
            # przód/tył
            if vx >= 0:
                do_forward (SPEED_LINEAR*ax, dur); publish_event("forward",  {"speed": SPEED_LINEAR*ax, "runtime": dur})
            else:
                do_backward(SPEED_LINEAR*ax, dur); publish_event("backward", {"speed": SPEED_LINEAR*ax, "runtime": dur})
        elif ay > 0:
            # sidestep (prawo/lewo) – jeśli FW nie wspiera, log pokaże brak metody
            if vy >= 0:
                do_right(SPEED_LINEAR*ay, dur);  publish_event("right", {"speed": SPEED_LINEAR*ay, "runtime": dur})
            else:
                do_left (SPEED_LINEAR*ay, dur);  publish_event("left",  {"speed": SPEED_LINEAR*ay, "runtime": dur})

        _schedule_deadman(dur)
        continue

    if topic == "cmd.stop":
        do_stop(); publish_event("stop", {})
        continue

    # STARE: zgodność wstecz (cmd.motion.*)
    spd = float(data.get("speed", 10.0))
    rt  = max(0.05, min(float(data.get("runtime", 0.6)), SAFE_MAX_DURATION))

    if   topic.endswith(".forward"):
        do_forward(spd, rt); publish_event("forward", {"speed": spd, "runtime": rt}); _schedule_deadman(rt)
    elif topic.endswith(".backward"):
        do_backward(spd, rt); publish_event("backward", {"speed": spd, "runtime": rt}); _schedule_deadman(rt)
    elif topic.endswith(".left"):
        do_left(spd, rt); publish_event("left", {"speed": spd, "runtime": rt}); _schedule_deadman(rt)
    elif topic.endswith(".right"):
        do_right(spd, rt); publish_event("right", {"speed": spd, "runtime": rt}); _schedule_deadman(rt)
    elif topic.endswith(".turn_left"):
        do_turn_left(spd, rt); publish_event("turn_left", {"speed": spd, "runtime": rt}); _schedule_deadman(rt)
    elif topic.endswith(".turn_right"):
        do_turn_right(spd, rt); publish_event("turn_right", {"speed": spd, "runtime": rt}); _schedule_deadman(rt)
    elif topic.endswith(".stop"):
        do_stop(); publish_event("stop", {})

print("[bridge] STOP", flush=True)
