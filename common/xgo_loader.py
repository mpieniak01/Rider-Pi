#!/usr/bin/env python3
"""
Utility for dynamically loading XGOClientRO from scripts/dev_xgo-client.py.

Since dev_xgo-client.py contains a hyphen in its filename, standard Python
imports fail. This module provides a shared function to load it dynamically.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os


def load_xgo_client_ro(repo_root: str | None = None):
    """
    Dynamically load and return the XGOClientRO class from scripts/dev_xgo-client.py.

    Args:
        repo_root: Optional path to the repository root. If not provided, will
                   attempt to auto-detect by searching for the scripts directory.

    Returns:
        The XGOClientRO class from dev_xgo-client.py.

    Raises:
        ImportError: If the file cannot be found or loaded.
    """
    if repo_root is None:
        # Try to auto-detect repo root by looking for scripts/dev_xgo-client.py
        # from the current file location
        current_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.abspath(os.path.join(current_dir, ".."))

    fpath = os.path.join(repo_root, "scripts", "dev_xgo-client.py")

    if not os.path.isfile(fpath):
        raise ImportError(f"dev_xgo-client.py not found at {fpath}")

    spec = importlib.util.spec_from_loader(
        "dev_xgo_client_mod",
        importlib.machinery.SourceFileLoader("dev_xgo_client_mod", fpath),
    )

    if not spec or not spec.loader:
        raise ImportError(f"Cannot create module spec for {fpath}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]

    if not hasattr(mod, "XGOClientRO"):
        raise ImportError(f"XGOClientRO class not found in {fpath}")

    return mod.XGOClientRO
