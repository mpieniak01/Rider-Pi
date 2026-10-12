#!/usr/bin/env python3
"""Hardware-free face render/RGB565 benchmark; no UART, LCD or bus imports."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def controller_class(reference):
    if not reference:
        from apps.ui.face.controller import FaceController

        return FaceController, None
    temporary = tempfile.TemporaryDirectory(prefix="rider-face-baseline-")
    folder = Path(temporary.name)
    files = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", reference, "apps/ui/face"], cwd=ROOT, text=True
    ).splitlines()
    for name in files:
        if not name.endswith(".py"):
            continue
        target = folder / Path(name).relative_to("apps/ui/face")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(["git", "show", reference + ":" + name], cwd=ROOT))
    package = importlib.util.spec_from_file_location("_baseline_face", folder / "__init__.py")
    module = importlib.util.module_from_spec(package)
    sys.modules[package.name] = module
    package.loader.exec_module(module)
    from _baseline_face.controller import FaceController

    return FaceController, temporary


def main():
    from apps.ui.face.characters import SKINS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref")
    parser.add_argument("--style", choices=["friendly", "minimal", "legacy"], default="friendly")
    parser.add_argument("--skin", choices=tuple(SKINS), default="none")
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--paced-seconds", type=float, default=3)
    args = parser.parse_args()
    if not 30 <= args.frames <= 3000 or not 0 <= args.paced_seconds <= 15:
        parser.error("frames: 30..3000, paced seconds: 0..15")
    from apps.ui.face.face_io import to_rgb565

    factory, temporary = controller_class(args.baseline_ref)
    try:
        face = factory(idle=False, style=args.style, skin=args.skin)
    except TypeError:
        face = factory(idle=False)
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    times = []

    def render(index):
        face.anim.state.eyes.dx = math.sin(index * 0.17) * 0.7
        face.anim.state.brows.lift = math.sin(index * 0.11) * 0.3
        face.anim.state.mouth.open = (math.sin(index * 0.31) + 1) * 0.25
        started = time.perf_counter()
        image = face.frame_image()
        raw = to_rgb565(image)
        elapsed = (time.perf_counter() - started) * 1000
        assert len(raw) == 240 * 240 * 2
        return elapsed

    for index in range(20):
        render(index)
    for index in range(args.frames):
        times.append(render(index))
    cpu_start, wall_start = time.process_time(), time.monotonic()
    index = 0
    while time.monotonic() - wall_start < args.paced_seconds:
        tick = time.monotonic()
        render(index)
        index += 1
        time.sleep(max(0, 1 / 12 - (time.monotonic() - tick)))
    wall, cpu = time.monotonic() - wall_start, time.process_time() - cpu_start
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    ordered = sorted(times)
    print(
        json.dumps(
            {
                "hardware_access": False,
                "style": "legacy" if args.baseline_ref else args.style,
                "skin": "none" if args.baseline_ref else args.skin,
                "baseline_ref": args.baseline_ref,
                "frames": len(times),
                "mean_ms": round(statistics.mean(times), 3),
                "p95_ms": round(ordered[math.ceil(len(times) * 0.95) - 1], 3),
                "cpu_one_core_percent_at_12fps": round(cpu / wall * 100, 2) if args.paced_seconds else None,
                "paced_wall_s": round(wall, 3),
                "process_peak_rss_mib": round(after / 1024, 2),
                "loop_peak_rss_growth_mib": round((after - before) / 1024, 2),
                "png_encodes": getattr(face.renderer, "encode_count", None),
            },
            indent=2,
        )
    )
    face.close() if hasattr(face, "close") else None
    if temporary:
        temporary.cleanup()


if __name__ == "__main__":
    main()
