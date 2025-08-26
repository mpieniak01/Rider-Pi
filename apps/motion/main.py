# apps/motion/main.py
"""
Pętla ruchu Rider-Pi:
- SUB ZeroMQ (topic 'motion') z brokera (XPUB) na tcp://127.0.0.1:5556
- sterowanie: {"type":"drive","lx":float,"az":float} / {"type":"stop"}
- bezpieczeństwo: MOTION_ENABLE / plik-flag, E-Stop, clamp prędkości
- watchdog: auto STOP po braku komend
- rampa prędkości (miękki start/stop)
- telemetria PUB 'motion.state' na broker (tcp://127.0.0.1:5555)
"""

import os
import time
import json
import logging
from typing import Optional

from apps.safety.estop import estop_triggered, motion_enabled, safe_speed

from common.pidlock import single_instance
_PID_FD = single_instance()

# ── ENV ───────────────────────────────────────────────────────────────────────
WATCHDOG_MS   = int(os.getenv("MOTION_WATCHDOG_MS", "500"))              # ms
LOOP_DT       = float(os.getenv("MOTION_LOOP_DT", "0.02"))               # 50 Hz
BUS_ADDR      = os.getenv("BUS_SUB_ADDR", "tcp://127.0.0.1:5556")        # SUB
BUS_TOPIC     = os.getenv("MOTION_TOPIC", "motion")
SPEED_LIMIT   = float(os.getenv("MOTION_SPEED_LIMIT", "0.6"))
LOG_LEVEL     = os.getenv("MOTION_LOG_LEVEL", "INFO").upper()

# rampa (jednostka: jednostki/s)
RAMP_LX       = float(os.getenv("MOTION_RAMP_LX", "1.0"))   # np. 1.0 m/s^2 (lub skala Twojej prędkości)
RAMP_AZ       = float(os.getenv("MOTION_RAMP_AZ", "2.0"))   # np. 2.0 rad/s^2
EPS           = float(os.getenv("MOTION_EPS", "0.01"))      # próg uznania „prawie zero”

# telemetria
STATE_PUB_ADDR   = os.getenv("BUS_PUB_ADDR", "tcp://127.0.0.1:5555")
STATE_TOPIC      = os.getenv("MOTION_STATE_TOPIC", "motion.state")
STATE_HZ         = float(os.getenv("MOTION_TELEM_HZ", "5.0"))

LOG = logging.getLogger("motion")

# ── Adapter (real/sim) ───────────────────────────────────────────────────────
class _SimAdapter:
    def __init__(self):
        self._moving = False

    def move(self, lx: float = 0.0, az: float = 0.0):
        self._moving = True
        LOG.info(f"[SIM] move lx={lx:.3f} az={az:.3f}")

    def stop(self):
        if self._moving:
            LOG.info("[SIM] STOP")
        self._moving = False

def _make_adapter() -> object:
    real_enabled = motion_enabled()
    if real_enabled:
        try:
            from apps.motion.xgo_adapter import XgoAdapter  # dostosuj ścieżkę jeśli potrzeba
            LOG.info("Init XgoAdapter (real movement ENABLED)")
            return XgoAdapter()
        except Exception as e:
            LOG.warning(f"XgoAdapter niedostępny ({e}), przełączam na symulację.")
    else:
        LOG.info("Ruch fizyczny wyłączony – tryb symulacji.")
    return _SimAdapter()

# ── Telemetria ───────────────────────────────────────────────────────────────
class MotionTelemetry:
    def __init__(self, addr: str, topic: str, rate_hz: float):
        self.addr = addr
        self.topic = topic.encode("utf-8")
        self.period = 1.0 / max(0.1, rate_hz)
        self.last_pub = 0.0
        self._ok = False
        self._ctx = None
        self._pub = None
        try:
            import zmq
            self._ctx = zmq.Context.instance()
            self._pub = self._ctx.socket(zmq.PUB)
            self._pub.connect(self.addr)
            self._ok = True
            time.sleep(0.1)  # rozgrzewka
            LOG.info(f"Telemetry PUB → {self.addr} topic='{topic}' @ {rate_hz} Hz")
        except Exception as e:
            LOG.warning(f"Telemetry disabled ({e})")

    def maybe_publish(self, state: dict):
        if not self._ok:
            return
        now = time.time()
        if now - self.last_pub < self.period:
            return
        self.last_pub = now
        try:
            payload = json.dumps(state, ensure_ascii=False).encode("utf-8")
            self._pub.send_multipart([self.topic, payload])
        except Exception as e:
            LOG.debug(f"Telemetry publish error: {e}")

# ── Kontroler z rampą ────────────────────────────────────────────────────────
class MotionController:
    def __init__(self, robot):
        self.robot = robot
        self.last_cmd_ts = time.time()
        self.stopped = True

        # cele (target) i wyjścia (out) dla rampy
        self.t_lx = 0.0
        self.t_az = 0.0
        self.o_lx = 0.0
        self.o_az = 0.0

    def _stop_immediate(self):
        """Natychmiastowe zatrzymanie i wyzerowanie."""
        self.t_lx = self.t_az = 0.0
        self.o_lx = self.o_az = 0.0
        try:
            self.robot.stop()
        finally:
            self.stopped = True
            LOG.info("MOTION: STOP")

    def stop(self):
        """Miękki STOP (rampa do zera)."""
        self.t_lx = self.t_az = 0.0

    def drive(self, lx: float, az: float):
        # Blokady bezpieczeństwa
        if not motion_enabled() or estop_triggered():
            self._stop_immediate()
            return

        # Ograniczenie komend
        lx = safe_speed(lx, SPEED_LIMIT)
        az = safe_speed(az, SPEED_LIMIT)

        # Ustaw cel rampy
        self.t_lx = lx
        self.t_az = az
        self.last_cmd_ts = time.time()

    def _approach(self, cur: float, tgt: float, rate: float, dt: float) -> float:
        delta = tgt - cur
        maxstep = rate * dt
        if   delta > maxstep: return cur + maxstep
        elif delta < -maxstep: return cur - maxstep
        else: return tgt

    def tick(self, dt: float):
        # twarde zatrzymanie gdy brak pozwolenia lub E-Stop:
        if not motion_enabled() or estop_triggered():
            if not self.stopped:
                self._stop_immediate()
            else:
                self.t_lx = self.t_az = 0.0
                self.o_lx = self.o_az = 0.0
            return

        # watchdog: wygaszaj target do 0, jeśli dawno nie było komendy
        if (time.time() - self.last_cmd_ts) * 1000.0 > WATCHDOG_MS:
            self.t_lx = 0.0
            self.t_az = 0.0

        # rampa do celu
        new_lx = self._approach(self.o_lx, self.t_lx, RAMP_LX, dt)
        new_az = self._approach(self.o_az, self.t_az, RAMP_AZ, dt)

        changed = (abs(new_lx - self.o_lx) > 1e-4) or (abs(new_az - self.o_az) > 1e-4)
        self.o_lx, self.o_az = new_lx, new_az

        if changed:
            if abs(self.o_lx) > EPS or abs(self.o_az) > EPS:
                self.robot.move(lx=self.o_lx, az=self.o_az)
                self.stopped = False
            else:
                if not self.stopped:
                    self._stop_immediate()

# ── MotionBus (SUB) ──────────────────────────────────────────────────────────
class MotionBus:
    """
    SUB ZeroMQ: odbiera ramki 'topic <json>'.
    """
    def __init__(self, addr: str, topic: str):
        self.addr = addr
        self.topic = topic.encode("utf-8")
        self._ctx = None
        self._sub = None
        self._poller = None
        self._ok = False
        self._init()

    def _init(self):
        try:
            import zmq
            self._ctx = zmq.Context.instance()
            self._sub = self._ctx.socket(zmq.SUB)
            # self._sub.setsockopt(zmq.CONFLATE, 1)  # opcjonalnie „ostatnia wygrywa”
            self._sub.connect(self.addr)
            self._sub.setsockopt(zmq.SUBSCRIBE, self.topic)
            self._poller = zmq.Poller()
            self._poller.register(self._sub, zmq.POLLIN)
            self._ok = True
            LOG.info(f"MotionBus SUB connected to {self.addr} topic='{self.topic.decode()}'")
        except Exception as e:
            LOG.warning(f"MotionBus niedostępny ({e}). Uruchamiam bez busa.")
            self._ok = False

    def recv_nowait(self) -> Optional[dict]:
        if not self._ok:
            return None
        try:
            import zmq
            socks = dict(self._poller.poll(timeout=0))
            if self._sub in socks and socks[self._sub] == zmq.POLLIN:
                raw = self._sub.recv_multipart()
                payload_bytes = raw[1] if len(raw) >= 2 else raw[-1]
                payload = payload_bytes.decode("utf-8", errors="replace").strip()
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    LOG.warning(f"Nieparsowalny payload: {payload[:200]}")
        except Exception as e:
            LOG.warning(f"Błąd odbioru z busa: {e}")
        return None

# ── Obsługa komend ───────────────────────────────────────────────────────────
def _handle_cmd(ctrl: MotionController, cmd: dict):
    LOG.debug(f"CMD: {cmd}")
    ctype = str(cmd.get("type", "")).lower()
    if ctype == "drive":
        lx = float(cmd.get("lx", 0.0))
        az = float(cmd.get("az", 0.0))
        ctrl.drive(lx=lx, az=az)
    elif ctype == "stop":
        ctrl.stop()
    else:
        LOG.debug(f"Nieznana komenda: {cmd}")

# ── Main loop ────────────────────────────────────────────────────────────────
def main():
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    robot = _make_adapter()
    ctrl = MotionController(robot)
    bus = MotionBus(BUS_ADDR, BUS_TOPIC)
    telem = MotionTelemetry(STATE_PUB_ADDR, STATE_TOPIC, STATE_HZ)

    LOG.info("Motion loop start")

    try:
        last = time.time()
        while True:
            # odbiór komend
            cmd = bus.recv_nowait()
            if cmd is not None:
                _handle_cmd(ctrl, cmd)

            # tick z dt
            now = time.time()
            dt = now - last
            last = now
            if dt <= 0 or dt > 1.0:
                dt = LOOP_DT  # sanity
            ctrl.tick(dt)

            # telemetria
            state = {
                "ts": time.time(),
                "enabled": bool(motion_enabled()),
                "estop": bool(estop_triggered()),
                "stopped": bool(ctrl.stopped),
                "target": {"lx": ctrl.t_lx, "az": ctrl.t_az},
                "output": {"lx": ctrl.o_lx, "az": ctrl.o_az},
                "last_cmd_age_ms": int((time.time() - ctrl.last_cmd_ts) * 1000.0),
                "watchdog_ms": WATCHDOG_MS,
                "ramp": {"lx": RAMP_LX, "az": RAMP_AZ},
                "limit": SPEED_LIMIT,
            }
            telem.maybe_publish(state)

            time.sleep(LOOP_DT)
    except KeyboardInterrupt:
        LOG.info("KeyboardInterrupt – zatrzymuję ruch.")
    except Exception as e:
        LOG.exception(f"Błąd w pętli motion: {e}")
    finally:
        try:
            ctrl.stop()
        except Exception:
            pass
        LOG.info("Motion loop stop")

if __name__ == "__main__":
    main()
