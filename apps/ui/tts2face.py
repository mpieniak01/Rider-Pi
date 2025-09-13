"""Compat stub for text-to-speech face hooks.

This module previously synchronized TTS with face animations. The new drawing
service exposes only static rendering and leaves animation to higher layers.
TODO: remove once callers migrate.
"""

from apps.draw.face_renderer import render_face  # noqa:F401

__all__ = ["render_face"]
