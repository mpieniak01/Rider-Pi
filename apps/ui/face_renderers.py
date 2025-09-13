"""Legacy compat wrapper for face renderer.

TODO: remove after migrating to :mod:`apps.draw.face_renderer`.
"""

from apps.draw.face_renderer import render_face, to_b64  # noqa:F401

__all__ = ["render_face", "to_b64"]
