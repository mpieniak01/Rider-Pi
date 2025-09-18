#!/usr/bin/env python3
"""Entry point kept for backwards compatibility."""

from .cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
