#!/usr/bin/env python3
"""Controlled LCD OFF after boot/renderer idle; never affects another owner."""

from __future__ import annotations

import json

from apps.ui.lcd_power import off_if_free


def main():
    result = off_if_free()
    print("[lcd-power]", json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
