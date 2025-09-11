#!/usr/bin/env python3
import os, sys, subprocess

SINK = os.getenv("PULSE_SINK", "1")

def run(cmd):
    subprocess.run(cmd, shell=True, check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def ensure_pulse():
    # uniknij mnożenia instancji
    run("sudo -u pi pulseaudio --check || sudo -u pi pulseaudio --start")

def set_percent(p):
    p = max(0, min(150, int(p)))
    ensure_pulse()
    run(f"sudo -u pi pactl set-sink-volume {SINK} {p}%")

def mute(on=True):
    ensure_pulse()
    run(f"sudo -u pi pactl set-sink-mute {SINK} {'1' if on else '0'}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: volume.py set <0..150> | mute on|off")
        sys.exit(1)
    if sys.argv[1] == "set":
        set_percent(sys.argv[2] if len(sys.argv)>2 else "50")
    elif sys.argv[1] == "mute":
        mute(sys.argv[2].lower() == "on")
