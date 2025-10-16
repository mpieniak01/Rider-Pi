#!/usr/bin/env python3
"""Entry point for choreographer module when run as a module or systemd service."""

from __future__ import annotations

from apps.choreographer.main import main

if __name__ == "__main__":
    main()
