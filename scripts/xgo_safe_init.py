#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xgo_safe_init.py — bezpieczny start/odczyt XGO:
- --backend xgolib  -> używa oryginalnego xgolib.XGO (może szarpnąć w __init__)
- --backend ro      -> używa naszej biblioteki XGOClientRO (zero ruchu)
"""

import os, time, sys, argparse

def fmt(x, d=1, suf=""):
    try: return f"{float(x):.{d}f}{suf}"
    except: return "—"

def pose_label(roll, pitch):
    try:
        if roll is None or pitch is None: return "—"
        r, p = abs(float(roll)), abs(float(pitch))
        if r<20 and p<20: return "upright"
        if r>60 or p>60:  return "fallen?"
        return "leaning"
    except: return "—"

def quietify_xgolib(dog):
    """
    Best-effort wyciszenie ruchów dla xgolib (i tak __init__ XGO robi reset()).
    """
    # zatrzymaj różne tryby jeśli istnieją
    for name in ("action_stop","motion_stop","stop_move","stop","standby","halt","gait_stop","disable_gait","stop_gait"):
        if hasattr(dog, name):
            try: getattr(dog, name)()
            except Exception: pass
    # próba wyzerowania prędkości
    for name in ("move","velocity","set_velocity","set_v","set_speed","move_x","move_y","turn","mark_time"):
        if hasattr(dog, name):
            try:
                fn = getattr(dog, name)
                try: fn(0,0,0)
                except TypeError:
                    try: fn(0,0,0,0)
                    except TypeError:
                        try: fn(0)
                        except TypeError:
                            pass
            except Exception:
                pass
    # tryb spoczynkowy (jeśli jest)
    for val in ("idle","rest","stand"):
        for name in ("set_mode","set_state","mode","state"):
            if hasattr(dog, name):
                try: getattr(dog, name)(val)
                except Exception: pass

def connect_xgolib():
    os.system("sudo chmod 666 /dev/ttyAMA0 /dev/serial0 2>/dev/null || true")
    from xgolib import XGO
    last_err = None
    for port in ("/dev/ttyAMA0","/dev/serial0"):
        for ver in ("xgorider","xgolite","xgomini"):
            try:
                dog = XGO(port=port, version=ver)
                return dog, port, ver
            except Exception as e:
                last_err = e
    raise RuntimeError(f"Nie mogę połączyć się przez xgolib: {last_err}")

def connect_ro(port="/dev/ttyAMA0", verbose=False):
    # import przez scripts. – zakładamy plik obok
    from scripts.xgo_client_ro import XGOClientRO
    dog = XGOClientRO(port=port, verbose=verbose)
    return dog, port, "ro"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["xgolib","ro"], default="xgolib")
    ap.add_argument("--port", default="/dev/ttyAMA0")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="(RO) pokaż ramki [tx]/[rx]")
    args = ap.parse_args()

    if args.backend == "xgolib":
        dog, port, ver = connect_xgolib()
        # Uwaga: XGO.__init__ robi reset() -> jednorazowe szarpnięcie jest niestety nie do uniknięcia.
        # Minimalizujemy dalsze ruchy:
        quietify_xgolib(dog)
        time.sleep(0.2)
        try: fw = dog.read_firmware()
        except Exception: fw = None
        try: batt = dog.read_battery()
        except Exception: batt = None
        try: roll = dog.read_roll()
        except Exception: roll = None
        try: pitch = dog.read_pitch()
        except Exception: pitch = None
        try: yaw = dog.read_yaw()
        except Exception: yaw = None

        print(f"[ok] fw: {fw} | battery: {fmt(batt,0,'%')} | roll: {fmt(roll,1,'°')} pitch: {fmt(pitch,1,'°')} yaw: {fmt(yaw,1,'°')} | pose: {pose_label(roll,pitch)}")
        if args.once: return

        try:
            while True:
                try: batt = dog.read_battery()
                except: batt = None
                try: roll = dog.read_roll()
                except: roll = None
                try: pitch = dog.read_pitch()
                except: pitch = None
                try: yaw = dog.read_yaw()
                except: yaw = None
                print(f"battery: {fmt(batt,0,'%')} | roll: {fmt(roll,1,'°')} pitch: {fmt(pitch,1,'°')} yaw: {fmt(yaw,1,'°')} | pose: {pose_label(roll,pitch)}")
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n[bye] przerwano.")
            return

    else:
        # backend 'ro' — ZERO ruchu, port trzymamy otwarty
        dog, port, ver = connect_ro(args.port, args.verbose)
        with dog:
            fw = dog.read_firmware()
            batt = dog.read_battery()
            roll = dog.read_roll()
            pitch = dog.read_pitch()
            yaw = dog.read_yaw()
            print(f"[ok] fw: {fw} | battery: {fmt(batt,0,'%')} | roll: {fmt(roll,1,'°')} pitch: {fmt(pitch,1,'°')} yaw: {fmt(yaw,1,'°')} | pose: {pose_label(roll,pitch)}")
            if args.once: return

            try:
                while True:
                    batt = dog.read_battery()
                    roll = dog.read_roll()
                    pitch = dog.read_pitch()
                    yaw = dog.read_yaw()
                    print(f"battery: {fmt(batt,0,'%')} | roll: {fmt(roll,1,'°')} pitch: {fmt(pitch,1,'°')} yaw: {fmt(yaw,1,'°')} | pose: {pose_label(roll,pitch)}")
                    time.sleep(1.0)
            except KeyboardInterrupt:
                print("\n[bye] przerwano.")

if __name__ == "__main__":
    main()
