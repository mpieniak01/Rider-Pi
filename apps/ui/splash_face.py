"""Compat stub for splash screen face module.

Rendering utilities have moved to :mod:`apps.draw`. This placeholder keeps
legacy imports working but provides no functionality.
TODO: remove after migration.
"""

from apps.draw.face_renderer import render_face  # noqa:F401

__all__ = ["render_face"]
