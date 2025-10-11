#!/usr/bin/env python3
from __future__ import annotations

"""Entry point kept for backwards compatibility."""

from .cli import main  # noqa: E402

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
