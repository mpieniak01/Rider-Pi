"""Deprecated face core module.

Functionality has moved to :mod:`apps.draw`. This file only re-exports the
new renderer for backward compatibility and should not be used in new code.
TODO: remove after refactor is complete.
"""

from apps.draw.face_renderer import render_face  # noqa:F401

__all__ = ["render_face"]
