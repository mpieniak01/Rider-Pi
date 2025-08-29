#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, time, sys

def fmt(x, d=1, suf=""):
    try: return f"{float(x):.{d}f}{suf}"
    except: return "—"

def quietify(dog):
    """
    Spróbuj zatrzymać wszystko, co może poruszać robotem – bez względu na wersję API.
    Każda komenda jest opcjonalna i zabezpieczona.
    """
    # potencjalne „stop”/„idle” w różnych API:
    for name in ("stop", "action_stop", "motion_stop", "stop_move", "standby", "halt"):
        if hasattr(dog, name):
            try: getattr(dog, name)()
            except Exception: pass

    # wyzeruj prędkości (różne nazwy):
    for name in ("move", "velocity", "set_velocity", "set_v", "set_speed"):
        if hasattr(dog, name):
            try:
                fn = getattr(dog, name)
                # obsłuż popularne sygnatury: (vx, vy, yaw) albo (x,y,yaw,spd)
                try: fn(0,0,0)        # 3-argumentowa
                except TypeError:
                    try: fn(0,0,0,0)  # 4-argumentowa
                    except TypeError: pass
            except Exception: pass

    # przełącz w spoczynkowy tryb, jeśli istnieje:
    for val in ("idle", "rest", "stand"):
        for name in ("set_mode", "set_state", "mode", "state"):
            if hasattr(dog, name):
                try: getattr(dog, name)(val)
                except Exception: pass

    # zatrzymaj ewentualny „gait”
    for name in ("gait_stop", "disable_gait", "stop_gait"):
        if hasattr(dog, name):
            try: getattr(dog, name)()
            except Exception: pass

def connect():
    # czasem potrzebne do UART:
    os.system("sudo chmod 666 /dev/ttyAMA0 /dev/serial0 2>/dev/null || true")
    from xgolib import XGO
    last_err = None
    for port in ("/dev/ttyAMA0", "/dev/serial0"):
        for ver in ("xgolite", "xgomini"):
            try:
                dog = XGO(port=port, version=ver)
                return dog, port, ver
            except Exception as e:
                last_err = e
    raise RuntimeError(f"Nie mogę połączyć się z XGO: {last_err}")

def main():
    dog, port, ver = connect()
    print(f"[OK] połączenie: port={port}, version={ver}")

    # >>> CICHY START – natychmiast zatrzymaj wszystko
    quietify(dog)
    time.sleep(0.2)
    # <<<

    # pokaż firmware (jeśli jest) – też w try/except
    try:
        fm = dog.read_firmware()
        print("[info] firmware:", fm)
    except Exception:
        pass

    print("Start odczytów (CTRL+C aby zakończyć)...")
    while True:
        try: batt = dog.read_battery()
        except Exception: batt = None

        try: roll  = dog.read_roll()
        except Exception: roll = None
        try: pitch = dog.read_pitch()
        except Exception: pitch = None
        try: yaw   = dog.read_yaw()
        except Exception: yaw = None

        pose = "—"
        try:
            if roll is not None and pitch is not None:
                r, p = abs(float(roll)), abs(float(pitch))
                pose = "upright" if (r<20 and p<20) else ("fallen?" if (r>60 or p>60) else "leaning")
        except: pass

        print(f"battery: {fmt(batt,0,'%')} | roll: {fmt(roll,1,'°')} pitch: {fmt(pitch,1,'°')} yaw: {fmt(yaw,1,'°')} | pose: {pose}")
        time.sleep(1.0)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt:
        print("\n[bye] przerwano.")
        sys.exit(0)
