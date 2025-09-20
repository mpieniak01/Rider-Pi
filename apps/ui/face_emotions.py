from __future__ import annotations

"""Legacy compat wrapper for face emotions.

TODO: remove after migrating to :mod:`apps.draw.face_emotions`.
"""

from apps.draw.face_emotions import ALLOWED, normalize_expr  # noqa: E402, F401

__all__ = ["ALLOWED", "normalize_expr"]
