#!/usr/bin/env python3
# tools/manual_drive.py
# Prosty trenażer impulsów: f/b/l/r/s/q + liczba (opcjonalnie).
# Spójny z apps/motion/xgo_adapter.py: impulsy blokujące (block=True),
# obroty realizowane vendorowo (turnleft/turnright przez ada.spin).

import os, sys
from apps.motion.xgo_adapter import XgoAdapter

HELP = """\
Komendy:
  f [v] [t]   - forward  (v: 0..1, t: sekundy)       np. "f 0.05 0.15"
  b [v] [t]   - backward (v: 0..1, t: sekundy)
  l [deg] [t] - left     (deg: stopnie, t: sekundy)  np. "l 22 0.45"
  r [deg] [t] - right
  s           - stop (awaryjny)
  i           - pokaż IMU (roll/pitch/yaw)
  h           - pomoc
  q           - wyjście

Domyślne gdy brak parametrów:
  f/b: v=$RIDER_SPEED_LIN (domyślnie 0.05), t=$RIDER_PULSE (domyślnie 0.15)
  l/r: deg=$RIDER_TURN_THETA (domyślnie 22), t=$RIDER_TURN_MINTIME (domyślnie 0.45)
Dodatkowo:
  prędkość obrotu bazowo z $RIDER_TURN_SPEED (domyślnie 0.30)
Włącz fizyczny ruch: export MOTION_ENABLE=1
"""

def env_float(name: str, default: float) -> float:
    try: return float(os.getenv(name, str(default)))
    except Exception: return default

def read_yaw(adapter: XgoAdapter) -> float:
    imu = adapter.imu() or {}
    try: return float(imu.get("yaw") or 0.0)
    except Exception: return 0.0

def main():
    # Nie wymuszamy ruchu – czytamy ustawienie użytkownika.
    os.environ.setdefault("MOTION_ENABLE", os.getenv("MOTION_ENABLE", "0"))

    ada = XgoAdapter()
    if not ada.ok():
        print("[ERR] XgoAdapter not OK (brak HW/lib). Upewnij się, że xgolib jest dostępny.")
        return

    # Domyślne parametry (po zmianach: mniejszy przesuw na biurku)
    v_def   = env_float("RIDER_SPEED_LIN",    0.05)  # 0..1 (mniejszy krok)
    t_lin   = env_float("RIDER_PULSE",        0.15)  # krótszy impuls f/b
    deg_def = env_float("RIDER_TURN_THETA",  22.00)  # °
    t_yaw   = env_float("RIDER_TURN_MINTIME", 0.45)  # s
    v_spin  = env_float("RIDER_TURN_SPEED",   0.30)  # 0..1 (mapowane do 20..70)

    print("Manual Drive (impulse). E-STOP: Ctrl+C  |  'h' po pomoc.")
    ada.stop()

    while True:
        try:
            sys.stdout.write("> "); sys.stdout.flush()
            line = sys.stdin.readline()
            if not line: break
            parts = line.strip().split()
            if not parts: continue

            cmd = parts[0].lower()

            if cmd in ("q", "quit", "exit"):
                break

            if cmd in ("h", "help", "?"):
                print(HELP); continue

            if cmd == "i":
                imu = ada.imu()
                if imu is None:
                    print("[IMU] brak danych")
                else:
                    print(f"[IMU] roll={imu.get('roll'):.2f} pitch={imu.get('pitch'):.2f} yaw={imu.get('yaw'):.2f}")
                continue

            if cmd == "s":
                ada.stop(); print("[STOP]"); continue

            if cmd in ("f","b"):
                v = v_def; t = t_lin
                if len(parts) >= 2:
                    try: v = max(0.0, min(1.0, float(parts[1])))
                    except Exception: pass
                if len(parts) >= 3:
                    try: t = max(0.05, float(parts[2]))
                    except Exception: pass
                direction = "forward" if cmd == "f" else "backward"
                print(f"[{direction}] v={v:.2f} t={t:.2f}")
                ada.drive(direction, v, t, block=True)  # block=True → adapter sam stopuje
                continue

            if cmd in ("l","r"):
                deg = deg_def; t = t_yaw
                if len(parts) >= 2:
                    try: deg = float(parts[1])  # info/log; adapter używa vendor turn step
                    except Exception: pass
                if len(parts) >= 3:
                    try: t = max(0.10, float(parts[2]))
                    except Exception: pass
                dir_ = "left" if cmd == "l" else "right"
                yaw0 = read_yaw(ada)
                print(f"[spin {dir_}] deg≈{deg:.1f} t={t:.2f} (yaw0={yaw0:.1f})")
                ada.spin(dir_, v_spin, dur=t, deg=deg, block=True)
                yaw1 = read_yaw(ada)
                d_yaw = yaw1 - yaw0
                print(f"[spin {dir_}] yaw1={yaw1:.1f} Δyaw={d_yaw:.1f}°")
                continue

            print("Nieznana komenda. 'h' po pomoc.")
        except KeyboardInterrupt:
            print("\n[ABORT]"); break
        except Exception as e:
            print(f"[ERR] {e}")
    ada.stop(); print("bye.")

if __name__ == "__main__":
    main()
