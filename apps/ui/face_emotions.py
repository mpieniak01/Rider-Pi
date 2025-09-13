"""Legacy compat wrapper for face emotions.

TODO: remove after migrating to :mod:`apps.draw.face_emotions`.
"""

from apps.draw.face_emotions import ALLOWED, normalize_expr  # noqa:F401

__all__ = ["ALLOWED", "normalize_expr"]
