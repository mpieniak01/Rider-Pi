"""Filesystem boundary for agent-invoked CLI tools, independent of network payloads."""

from __future__ import annotations

import os
from pathlib import Path

from common.secure_files import atomic_write


def output_path(value):
    base = os.path.realpath(os.getcwd())
    resolved = os.path.realpath(os.fspath(value))
    if base == os.path.sep or (resolved != base and not resolved.startswith(base + os.path.sep)):
        raise ValueError("cli_path_outside_working_directory")
    return Path(resolved)


def write_output(value, content):
    path = output_path(value)
    atomic_write(path, lambda stream: stream.write(content), replace=False)
