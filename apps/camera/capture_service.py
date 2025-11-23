#!/usr/bin/env python3
"""
Unified camera capture service.

Obsługuje tryby:
- raw  → dawny rider-cam-preview (apps.camera.preview_lcd)
- edge → dawny rider-edge-preview (apps.vision.edge_preview)
- ssd  → wariant z nakładką SSD (apps.camera.preview_lcd_ssd)

Tryb wybierany przez zmienną środowiskową CAPTURE_MODE=<raw|edge|ssd>.
"""

from __future__ import annotations

import importlib
import os
import runpy
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class ModeConfig:
    module: str
    entrypoint: str | None = None  # None → uruchom moduł jako __main__


MODE_ALIASES = {
    "": "raw",
    "cam": "raw",
    "camera": "raw",
    "preview": "raw",
}

MODE_MAP: dict[str, ModeConfig] = {
    "raw": ModeConfig("apps.camera.preview_lcd", "main"),
    "ssd": ModeConfig("apps.camera.preview_lcd_ssd", "main"),
    "edge": ModeConfig("apps.vision.edge_preview", None),  # brak main(), uruchamiamy top-level
}


def _normalize_mode(value: str | None) -> str:
    mode = (value or "").strip().lower()
    if mode in MODE_ALIASES:
        return MODE_ALIASES[mode]
    return mode or "raw"


def _run_mode(cfg: ModeConfig) -> int:
    if cfg.entrypoint is None:
        runpy.run_module(cfg.module, run_name="__main__")
        return 0
    module = importlib.import_module(cfg.module)
    target = getattr(module, cfg.entrypoint, None)
    if target is None:
        raise RuntimeError(f"Entrypoint {cfg.entrypoint!r} not found in {cfg.module}")
    result = target()
    return int(result) if isinstance(result, int) else 0


def main() -> int:
    mode = _normalize_mode(os.getenv("CAPTURE_MODE"))
    cfg = MODE_MAP.get(mode)
    if not cfg:
        print(f"[capture] Unsupported CAPTURE_MODE={mode!r}. Allowed: {', '.join(sorted(MODE_MAP))}", file=sys.stderr)
        return 2

    print(f"[capture] starting mode={mode} ({cfg.module})", flush=True)
    try:
        return _run_mode(cfg)
    except KeyboardInterrupt:
        return 0
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 0
    except Exception as exc:  # pragma: no cover - zależne od środowiska kamer
        print(f"[capture] fatal error in mode={mode}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
