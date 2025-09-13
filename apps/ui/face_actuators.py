"""Compat stub for removed hardware-specific face actuators.

The new drawing pipeline lives in :mod:`apps.draw.face_renderer` and does not
handle physical actuators. This module is kept for legacy imports only.
TODO: remove once deprecated.
"""

from apps.draw.face_renderer import render_face  # noqa:F401

__all__ = ["render_face"]
