#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rider-Pi — motion_bridge
Mostek: odbiera z busa (ZMQ) polecenia `cmd.motion.*` i wykonuje ruch XGO.

Topics IN (SUB):
  - cmd.motion.forward        { "speed": float, "runtime": float }
  - cmd.motion.backward       { "speed": float, "runtime": float }
  - cmd.motion.left           { "speed": float, "runtime": float }
  - cmd.motion.right          { "speed": float, "runtime": float }
  - cmd.motion.turn_left      { "speed": float, "runtime": float }
  - cmd.motion.turn_right     { "speed": float, "runtime": float }
  - cmd.motion.stop           {}
  - cmd.motion.demo           { "kind": "trajectory"|"spin", "speed": float }

Topics OUT (PUB):
  - motion.bridge.heartbeat   { "ts": float, "xgo_ok": bool, "dry_run": bool }
  - motion.bridge.event       { "ts": float, "event": str, "detail": {...} }

ENV:
  BUS_PUB_PORT (default 5555)
  BUS_SUB_PORT (default 5556)
  XGO_PORT     (default "/dev/ttyAMA0")
  XGO_BAUD     (default 115200)
  LOG_EVERY    (default 10)
"""

import os, time, json, threading, signal
from typing import Optional

# ---------- ZMQ ----------
try:
    import zmq
except Exception as e:
    print("[motion_bridge] pyzmq missing:", e, flush=True)
    zmq = None  # type: ignore

BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))

ZMQ_ADDR_PUB = f"tcp://127.0.0.1:{BUS_PUB_PORT}"
ZMQ_ADDR_SUB = f"tcp://127.0.0.1:{BUS_SUB_PORT}"

PUB = None
SUB = None

def zmq_pub():
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.PUB)
    s.connect(ZMQ_ADDR_PUB)
    return s

def zmq_sub():
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.SUB)
    s.connect(ZMQ_ADDR_SUB)
    for t in (
        "cmd.motion.forward",
        "cmd.motion.backward",
        "cmd.motion.left",
        "cmd.motion.right",
        "cmd.motion.turn_left",
        "cmd.motion.turn_right",
        "cmd.motion.stop",
        "cmd.motion.demo",
    ):
        s.setsockopt_string(zmq.SUBSCRIBE, t)
    return s

def bus_pub(topic: str, payload: dict):
    try:
        PUB.send_string(f"{topic} {json.dumps(payload, ensure_ascii=False)}")
    except Exception as e:
        print(f"[motion_bridge] PUB err: {e}", flush=True)

# ---------- XGO control (best-effort) ----------
XGO = None
try:
    # próbujemy kilka możliwych ścieżek
    from scripts.xgo import XGO as _XGO  # noqa: F401
    XGO = _XGO
except Exception:
    try:
        from xgo import XGO as _XGO  # noqa: F401
        XGO = _XGO
    except Exception:
        XGO = None

XGO_PORT = os.getenv("XGO_PORT", "/dev/ttyAMA0")
XGO_BAUD = int(os.getenv("XGO_BAUD", "115200"))

class XgoAdapter:
    """Cienka warstwa nad XGO; fallback do dry-run jeśli brak biblioteki/urządzenia."""
    def __init__(self):
        self.dry_run = False
        self.dev = None
        if XGO is None:
            print("[motion_bridge] XGO lib not found — DRY RUN mode", flush=True)
            self.dry_run = True
            return
        try:
            self.dev = XGO(port=XGO_PORT, baud=XGO_BAUD, version="xgorider", verbose=False)
            print(f"[motion_bridge] XGO connected on {XGO_PORT}", flush=True)
        except Exception as e:
            print(f"[motion_bridge] XGO init failed ({e}) — DRY RUN", flush=True)
            self.dry_run = True

    def forward(self, speed: float, runtime: float=0.0):
        if self.dry_run: 
            return
        try:
            self.dev.move_x(abs(speed), runtime=runtime)
        except Exception as e:
            print("[motion_bridge] forward err:", e, flush=True)

    def backward(self, speed: float, runtime: float=0.0):
        if self.dry_run: 
            return
        try:
            self.dev.move_x(-abs(speed), runtime=runtime)
        except Exception as e:
            print("[motion_bridge] backward err:", e, flush=True)

    def left(self, speed: float, runtime: float=0.0):
        if self.dry_run: 
            return
        try:
            self.dev.move_y(abs(speed), runtime=runtime)
        except Exception as e:
            print("[motion_bridge] left err:", e, flush=True)

    def right(self, speed: float, runtime: float=0.0):
        if self.dry_run: 
            return
        try:
            self.dev.move_y(-abs(speed), runtime=runtime)
        except Exception as e:
            print("[motion_bridge] right err:", e, flush=True)

    def turn_left(self, speed: float, runtime: float=0.0):
        if self.dry_run: 
            return
        try:
            self.dev.turn(abs(speed), runtime=runtime)
        except Exception as e:
            print("[motion_bridge] turn_left err:", e, flush=True)

    def turn_right(self, speed: float, runtime: float=0.0):
        if self.dry_run: 
            return
        try:
            self.dev.turn(-abs(speed), runtime=runtime)
        except Exception as e:
            print("[motion_bridge] turn_right err:", e, flush=True)

    def stop(self):
        if self.dry_run: 
            return
        try:
            # „zero” wszystkie wektory prędkości
            self.dev.move_x(0)
            self.dev.move_y(0)
            self.dev.turn(0)
        except Exception as e:
            print("[motion_bridge] stop err:", e, flush=True)

    def demo_trajectory(self, speed: float=12.0):
        """Prosta trajektoria demo: przód → lewo → tył → prawo → spin."""
        if self.dry_run:
            return
        try:
            self.forward(speed, runtime=1.2)
            time.sleep(0.2)
            self.left(speed*0.7, runtime=0.8)
            time.sleep(0.2)
            self.backward(speed, runtime=1.2)
            time.sleep(0.2)
            self.right(speed*0.7, runtime=0.8)
            time.sleep(0.2)
            self.turn_left(speed*2.0, runtime=1.0)
            self.stop()
        except Exception as e:
            print("[motion_bridge] demo err:", e, flush=True)

# ---------- Bridge logic ----------
LOG_EVERY = int(os.getenv("LOG_EVERY", "10"))

class MotionBridge:
    def __init__(self):
        if zmq is None:
            raise RuntimeError("pyzmq required")
        self.xgo = XgoAdapter()
        self._running = True
        self._frame = 0

    def _parse(self, payload: str) -> dict:
        try:
            return json.loads(payload)
        except Exception:
            return {}

    def handle(self, topic: str, payload: str):
        self._frame += 1
        data = self._parse(payload)
        spd = float(data.get("speed", 12.0))
        rt  = float(data.get("runtime", 0.8))
        if topic.endswith(".forward"):
            self.xgo.forward(spd, rt)
            bus_pub("motion.bridge.event", {"ts": time.time(), "event": "forward", "detail": {"speed": spd, "runtime": rt}})
        elif topic.endswith(".backward"):
            self.xgo.backward(spd, rt)
            bus_pub("motion.bridge.event", {"ts": time.time(), "event": "backward", "detail": {"speed": spd, "runtime": rt}})
        elif topic.endswith(".left"):
            self.xgo.left(spd, rt)
            bus_pub("motion.bridge.event", {"ts": time.time(), "event": "left", "detail": {"speed": spd, "runtime": rt}})
        elif topic.endswith(".right"):
            self.xgo.right(spd, rt)
            bus_pub("motion.bridge.event", {"ts": time.time(), "event": "right", "detail": {"speed": spd, "runtime": rt}})
        elif topic.endswith(".turn_left"):
            self.xgo.turn_left(spd, rt)
            bus_pub("motion.bridge.event", {"ts": time.time(), "event": "turn_left", "detail": {"speed": spd, "runtime": rt}})
        elif topic.endswith(".turn_right"):
            self.xgo.turn_right(spd, rt)
            bus_pub("motion.bridge.event", {"ts": time.time(), "event": "turn_right", "detail": {"speed": spd, "runtime": rt}})
        elif topic.endswith(".stop"):
            self.xgo.stop()
            bus_pub("motion.bridge.event", {"ts": time.time(), "event": "stop", "detail": {}})
        elif topic.endswith(".demo"):
            kind = (data.get("kind") or "trajectory").lower()
            if kind == "trajectory":
                self.xgo.demo_trajectory(spd)
                bus_pub("motion.bridge.event", {"ts": time.time(), "event": "demo.trajectory", "detail": {"speed": spd}})
            elif kind == "spin":
                self.xgo.turn_left(spd*2.0, 1.2)
                self.xgo.stop()
                bus_pub("motion.bridge.event", {"ts": time.time(), "event": "demo.spin", "detail": {"speed": spd}})
            else:
                bus_pub("motion.bridge.event", {"ts": time.time(), "event": "demo.unknown", "detail": {"kind": kind}})

        if LOG_EVERY > 0 and (self._frame % LOG_EVERY == 0):
            print(f"[motion_bridge] handled {self._frame} cmds", flush=True)

    def hb_loop(self):
        while self._running:
            try:
                bus_pub("motion.bridge.heartbeat", {
                    "ts": time.time(),
                    "xgo_ok": (not self.xgo.dry_run),
                    "dry_run": bool(self.xgo.dry_run)
                })
            except Exception:
                pass
            time.sleep(2.0)

    def rx_loop(self):
        while self._running:
            try:
                raw = SUB.recv_string()
                if " " in raw:
                    topic, payload = raw.split(" ", 1)
                else:
                    topic, payload = raw, "{}"
                if not topic.startswith("cmd.motion."):
                    continue
                self.handle(topic, payload)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print("[motion_bridge] rx err:", e, flush=True)
                time.sleep(0.05)

    def stop(self):
        self._running = False
        try:
            self.xgo.stop()
        except Exception:
            pass

# ---------- main ----------
def main():
    global PUB, SUB
    if zmq is None:
        raise SystemExit("pyzmq is required for motion_bridge")

    PUB = zmq_pub()
    SUB = zmq_sub()

    bridge = MotionBridge()

    # graceful shutdown
    def _sig(*_):
        print("[motion_bridge] SIG received, stopping...", flush=True)
        bridge.stop()
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    threading.Thread(target=bridge.hb_loop, daemon=True).start()
    print("[motion_bridge] started (listening cmd.motion.*)", flush=True)
    bridge.rx_loop()
    print("[motion_bridge] exit", flush=True)

if __name__ == "__main__":
    import threading
    main()
