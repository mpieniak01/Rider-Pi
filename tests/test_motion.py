#!/usr/bin/env python3
# tests/test_motion.py
"""
Prosty tester XgoAdapter:
 - naprzód, wstecz
 - skręt w lewo, skręt w prawo
 - stop, IMU, bateria
"""

import time
from apps.motion.xgo_adapter import XgoAdapter

def main():
    ada = XgoAdapter()
    if not ada.ok():
        print("[ERR] Adapter/XGO niedostępny.")
        return

    print("[INFO] Start testów ruchu (E-STOP: Ctrl+C)")

    print("\n[Test] STOP")
    ada.stop(); time.sleep(0.5)

    print("\n[Test] Naprzód 0.3s")
    ada.drive("forward", 0.2, dur=0.3, block=True); time.sleep(0.5)

    print("\n[Test] Wstecz 0.3s")
    ada.drive("backward", 0.2, dur=0.3, block=True); time.sleep(0.5)

    print("\n[Test] Skręt w LEWO 0.5s")
    ada.spin("left", 0.5, dur=0.5, block=True); time.sleep(0.5)

    print("\n[Test] Skręt w PRAWO 0.5s")
    ada.spin("right", 0.5, dur=0.5, block=True); time.sleep(0.5)

    print("\n[Test] Ponownie STOP")
    ada.stop(); time.sleep(0.5)

    print("\n[INFO] Telemetria:")
    print("Battery:", ada.battery())
    print("IMU:", ada.imu())

    print("\n[INFO] Koniec testów.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[ABORT] ręczne przerwanie")
