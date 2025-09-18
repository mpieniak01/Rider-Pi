#!/usr/bin/env python3
"""
Proste menu (CLI) dla Rider-Pi:
- Demo trajectory (SAFE) — tymczasowo włącza ruch plikiem-flagą, uruchamia demo, po demie wyłącza.
- Szybkie testy drive/stop przez broker.
- E-Stop ON/OFF przez plik-flagę (działa z usługą systemd).

Uwaga: Motion jako usługa czyta:
  - /home/pi/robot/data/flags/motion.enable   → pozwolenie na ruch
  - /home/pi/robot/data/flags/estop.on        → twardy E-Stop
"""

import os
import time
import json
import subprocess
from pathlib import Path

BASE_DIR = Path("/home/pi/robot")
FLAGS_DIR = BASE_DIR / "data" / "flags"
FLAGS_DIR.mkdir(parents=True, exist_ok=True)

MOTION_ENABLE_FLAG = FLAGS_DIR / "motion.enable"
ESTOP_FLAG = FLAGS_DIR / "estop.on"

PUB_ADDR = os.getenv("BUS_PUB_ADDR", "tcp://127.0.0.1:5555")
TOPIC = os.getenv("MOTION_TOPIC", "motion")

def _pub(msg: dict):
    # minimalny publisher (ZeroMQ) – bez zewnętrznych zależności w menu
    import zmq
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.PUB)
    s.connect(PUB_ADDR)
    time.sleep(0.15)  # rozgrzewka subów
    s.send_multipart([TOPIC.encode(), json.dumps(msg).encode("utf-8")])

def motion_enable(on: bool):
    if on:
        MOTION_ENABLE_FLAG.touch()
    else:
        try:
            MOTION_ENABLE_FLAG.unlink()
        except FileNotFoundError:
            pass

def estop_set(on: bool):
    if on:
        ESTOP_FLAG.touch()
    else:
        try:
            ESTOP_FLAG.unlink()
        except FileNotFoundError:
            pass
    # zawsze wyślij STOP dla pewności
    _pub({"type": "stop"})

def demo_trajectory_safe():
    print("[MENU] Enabling motion (flag) and running demo…")
    motion_enable(True)
    try:
        env = os.environ.copy()
        # PUB_ADDR/TOPIC zgodne z usługą/brokerem
        env["BUS_PUB_ADDR"] = PUB_ADDR
        env["MOTION_TOPIC"] = TOPIC
        subprocess.run(
            ["python3", "-u", str(BASE_DIR / "apps" / "demos" / "trajectory.py")],
            env=env, check=True
        )
    finally:
        print("[MENU] Demo done. Disabling motion (flag).")
        motion_enable(False)

def quick_forward_1s():
    print("[MENU] drive forward 1s")
    t0 = time.time()
    while time.time() - t0 < 1.0:
        _pub({"type": "drive", "lx": 0.25, "az": 0.0})
        time.sleep(0.1)
    _pub({"type": "stop"})

def quick_spin_1s():
    print("[MENU] spin right 1s")
    t0 = time.time()
    while time.time() - t0 < 1.0:
        _pub({"type": "drive", "lx": 0.0, "az": 0.25})
        time.sleep(0.1)
    _pub({"type": "stop"})

def show_status():
    m = MOTION_ENABLE_FLAG.exists()
    e = ESTOP_FLAG.exists()
    print(f"[STATUS] motion_enable_flag={m}  estop_flag={e}  PUB_ADDR={PUB_ADDR}  TOPIC={TOPIC}")

def main():
    while True:
        print("\n==== Rider-Pi Menu ====")
        print("1) Demo trajectory (SAFE)")
        print("2) Quick: forward 1s")
        print("3) Quick: spin right 1s")
        print("4) STOP now")
        print("5) E-Stop ON")
        print("6) E-Stop OFF")
        print("7) Show status")
        print("0) Exit")
        try:
            choice = input("Select: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if choice == "1":
            demo_trajectory_safe()
        elif choice == "2":
            quick_forward_1s()
        elif choice == "3":
            quick_spin_1s()
        elif choice == "4":
            _pub({"type": "stop"})
            print("[MENU] STOP sent")
        elif choice == "5":
            estop_set(True)
        elif choice == "6":
            estop_set(False)
        elif choice == "7":
            show_status()
        elif choice == "0":
            print("Bye.")
            break
        else:
            print("Unknown option.")

if __name__ == "__main__":
    main()
