# apps/demos/trajectory.py
import os
import time
import json

PUB_ADDR = os.getenv("BUS_PUB_ADDR", "tcp://127.0.0.1:5555")
TOPIC = os.getenv("MOTION_TOPIC", "motion")
RATE_HZ = float(os.getenv("DEMO_RATE_HZ", "10"))   # częstotliwość wysyłki
DT = 1.0 / RATE_HZ

SPEED_FWD = float(os.getenv("DEMO_SPEED_FWD", "0.25"))
SPEED_ROT = float(os.getenv("DEMO_SPEED_ROT", "0.25"))
SEG_SEC = float(os.getenv("DEMO_SEG_SEC", "2.0"))

def _mk_pub(addr: str):
    import zmq
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.PUB)
    sock.connect(addr)
    return sock

def _send(sock, msg: dict):
    payload = json.dumps(msg).encode("utf-8")
    sock.send_multipart([TOPIC.encode("utf-8"), payload])

def _drive_for(sock, lx: float, az: float, dur: float):
    t0 = time.time()
    while time.time() - t0 < dur:
        _send(sock, {"type": "drive", "lx": lx, "az": az})
        time.sleep(DT)

def main():
    print(f"[DEMO] Connecting PUB to {PUB_ADDR} topic='{TOPIC}'")
    sock = _mk_pub(PUB_ADDR)

    # “przebudzenie” subskrybentów
    time.sleep(0.2)

    try:
        print("[DEMO] forward")
        _drive_for(sock, SPEED_FWD, 0.0, SEG_SEC)

        print("[DEMO] spin right")
        _drive_for(sock, 0.0, SPEED_ROT, SEG_SEC)

        print("[DEMO] backward")
        _drive_for(sock, -SPEED_FWD, 0.0, SEG_SEC)

        print("[DEMO] stop")
        _send(sock, {"type": "stop"})
        time.sleep(0.1)
    finally:
        # dodatkowy stop na wszelki wypadek
        _send(sock, {"type": "stop"})
        print("[DEMO] done")

if __name__ == "__main__":
    main()
