"""Deprecated face orchestrator entrypoint.

The dynamic face application was removed in favour of a lightweight drawing
API. This module now only exposes the :func:`render_face` helper for backward
compatibility. Running it as a script will print a short message and exit.
TODO: remove after migration.
"""

from __future__ import annotations

from apps.draw.face_renderer import render_face  # noqa:F401

__all__ = ["render_face"]


def main() -> None:  # pragma: no cover - compatibility shim
    print("apps.ui.face is deprecated; use services.api_core.face_api instead.")


if __name__ == "__main__":  # pragma: no cover - script behaviour
    main()
