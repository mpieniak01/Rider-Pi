#!/usr/bin/env python3
"""
Jupyter Lab runner with TOML configuration support.

This wrapper reads configuration from jupyter.toml and starts Jupyter Lab
with the configured parameters.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

try:
    import tomllib  # type: ignore[attr-defined]
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore


def _repo_root() -> Path:
    """Get repository root directory."""
    return Path(__file__).resolve().parents[1]


def _discover_config_path() -> Path:
    """Discover Jupyter configuration file path."""
    # 1. ENV override
    env_path = os.getenv("JUPYTER_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    # 2. local/jupyter.toml
    root = _repo_root()
    local = root / "config" / "local" / "jupyter.toml"
    if local.exists():
        return local

    # 3. config/jupyter.toml
    config = root / "config" / "jupyter.toml"
    if config.exists():
        return config

    # 4. config/jupyter.toml.example (fallback)
    example = root / "config" / "jupyter.toml.example"
    if example.exists():
        return example

    # Return config path even if it doesn't exist
    return config


def _read_toml(path: Path) -> dict:
    """Read TOML file and return parsed data."""
    if tomllib is None or not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f) or {}
    except Exception:
        return {}


def main():
    """Load config and start Jupyter Lab."""
    # Load configuration
    config_path = _discover_config_path()
    data = _read_toml(config_path)
    jupyter_config = data.get("jupyter", {})

    # Extract configuration with defaults
    ip = jupyter_config.get("ip", "0.0.0.0")
    port = jupyter_config.get("port", 8888)
    notebook_dir = jupyter_config.get("notebook_dir", "/home/pi")
    bash_profile = jupyter_config.get("bash_profile", "")

    # Allow ENV overrides
    ip = os.getenv("JUPYTER_IP", ip)
    port = int(os.getenv("JUPYTER_PORT", str(port)))
    notebook_dir = os.getenv("JUPYTER_NOTEBOOK_DIR", notebook_dir)
    bash_profile = os.getenv("BASH_PROFILE", bash_profile)

    # Build Jupyter command
    cmd = [
        sys.executable,
        "-m",
        "jupyter",
        "lab",
        f"--notebook-dir={notebook_dir}",
        f"--ip={ip}",
        "--no-browser",
        f"--port={port}",
    ]

    # If bash profile specified and exists, source it before running
    if bash_profile and Path(bash_profile).exists():
        # Use bash to source the profile and then exec jupyter
        bash_cmd = f'source "{bash_profile}" && exec {" ".join(cmd)}'
        cmd = ["/bin/bash", "-c", bash_cmd]

    print(f"[jupyter_runner] Starting Jupyter Lab: {cmd}", flush=True)
    print(f"[jupyter_runner] Config: {config_path}", flush=True)
    print(f"[jupyter_runner] notebook_dir={notebook_dir}, ip={ip}, port={port}", flush=True)

    # Execute Jupyter Lab
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        print("\n[jupyter_runner] Shutting down...", flush=True)
        return 0
    except Exception as e:
        print(f"[jupyter_runner] Error: {e}", file=sys.stderr, flush=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
