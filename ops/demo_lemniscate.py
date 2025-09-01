#!/usr/bin/env python3
# ops/demo_lemniscate.py
# Proste demo „ósemki” (lemniskata) na prymitywach XgoAdapter:
# w każdej iteracji: krótki yaw + krótki forward; po N krokach zmiana kierunku yaw.

import os
import time
from apps.motion.xgo_adapter import XgoAdapter

def main():
    os.environ.setdefault("MOTION_ENABLE", "1")
    ada = XgoAdapter()
    if not ada.ok():
        print("[ERR] XgoAdapter not OK")
        return

    steps_per_loop = int(os.getenv("LEM_STEPS", "24"))
    loops = int(os.getenv("LEM_LOOPS", "2"))
    yaw_speed = float(os.getenv("LEM_YAW_SPEED", "0.20"))
    drive_speed = float(os.getenv("LEM_DRIVE_SPEED", "0.10"))
    yaw_dur = float(os.getenv("LEM_YAW_DUR", os.getenv("MOTION_YAW_IMPULSE_SEC", "0.18")))
    drive_dur = float(os.getenv("LEM_DRIVE_DUR", os.getenv("MOTION_DRIVE_IMPULSE_SEC", "0.15")))
    pause = float(os.getenv("LEM_PAUSE", "0.02"))

    try:
        ada.stop()
        for loop in range(loops):
            yaw_dir = "left" if (loop % 2 == 0) else "right"
            print(f"[LEM] loop {loop+1}/{loops} yaw={yaw_dir}")
            for _ in range(steps_per_loop):
                ada.spin(yaw_dir, yaw_speed, dur=yaw_dur, deg=None, block=False)
                time.sleep(pause)
                ada.drive("forward", drive_speed, dur=drive_dur, block=False)
                time.sleep(pause)
        ada.stop(); print("[LEM] done")
    except KeyboardInterrupt:
        ada.stop(); print("[LEM] aborted")

if __name__ == "__main__":
    main()
