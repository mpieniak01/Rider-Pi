#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps/demos/trajectory.py — prosta trajektoria:
  drive(fwd, 0.4, 1.2s) → spin(left, 0.5, 0.8s) → drive(fwd, 0.3, 0.8s) → stop
"""
import os, sys, time

PROJ_ROOT = "/home/pi/robot"
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)

from common.bus import BusPub
PUB = BusPub()

def pub(topic, payload):
    for m in ("send","publish","pub"):
        if hasattr(PUB, m): return getattr(PUB, m)(topic, payload)

def step_drive(dir_, speed, dur):
    pub("motion.cmd", {"type":"drive","dir":dir_,"speed":float(speed),"dur":float(dur)})

def step_spin(dir_, speed, dur):
    pub("motion.cmd", {"type":"spin","dir":dir_,"speed":float(speed),"dur":float(dur)})

def step_stop():
    pub("motion.cmd", {"type":"stop"})

def log(msg): print(time.strftime("[%H:%M:%S]"), msg, flush=True)

def main():
    log("Demo trajectory: start")
    try:
        step_stop(); time.sleep(0.1)
        step_drive("forward", 0.4, 1.2);   time.sleep(1.25)
        step_spin("left",    0.5, 0.8);    time.sleep(0.85)
        step_drive("forward",0.3, 0.8);    time.sleep(0.85)
        step_stop(); time.sleep(0.1)
        log("Demo trajectory: done")
        # zostaw chwilę na publikację ostatnich motion.state
        time.sleep(0.5)
    except KeyboardInterrupt:
        step_stop()
    finally:
        log("Demo trajectory: bye")

if __name__ == "__main__":
    main()
