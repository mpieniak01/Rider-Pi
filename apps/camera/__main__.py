#!/usr/bin/env python3
from __future__ import annotations
import os, sys, argparse

PROJ_ROOT = "/home/pi/robot"
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)

# Uruchamiamy właściwy preview
from apps.camera.preview_lcd_takeover import main as preview_main


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rider-Pi camera preview launcher")
    p.add_argument("--human", type=int, choices=(0,1), help="detekcja twarzy 0/1")
    p.add_argument("--every", type=int, help="co ile klatek sprawdzac twarze")
    p.add_argument("--rot", type=int, choices=(0,90,180,270), help="rotacja 0/90/180/270")
    p.add_argument("--skip-v4l2", action="store_true", help="pomin V4L2, wymusz Picamera2")
    p.add_argument("--warmup", type=int, help="rozgrzewka klatek (Picamera2)")
    p.add_argument("--alpha", type=float, help="jasnosc (OpenCV convertScaleAbs alpha)")
    p.add_argument("--beta", type=float, help="offset jasnosci (beta)")
    return p.parse_args()


def main() -> int:
    a = parse_args()
    if a.human is not None:
        os.environ["VISION_HUMAN"] = str(int(a.human))
    if a.every is not None:
        os.environ["VISION_FACE_EVERY"] = str(int(a.every))
    if a.rot is not None:
        os.environ["PREVIEW_ROT"] = str(int(a.rot))
    if a.skip_v4l2:
        os.environ["SKIP_V4L2"] = "1"
    if a.warmup is not None:
        os.environ["PREVIEW_WARMUP"] = str(int(a.warmup))
    if a.alpha is not None:
        os.environ["PREVIEW_ALPHA"] = str(float(a.alpha))
    if a.beta is not None:
        os.environ["PREVIEW_BETA"] = str(float(a.beta))
    return preview_main()


if __name__ == "__main__":
    sys.exit(main())
