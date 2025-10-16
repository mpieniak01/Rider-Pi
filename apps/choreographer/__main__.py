#!/usr/bin/env python3
from __future__ import annotations

"""Entry point for choreographer module when run as a module or systemd service."""

from apps.choreographer.main import main

if __name__ == "__main__":
    main()
