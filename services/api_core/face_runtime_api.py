"""Every HTTP face alias delegates to one runtime and orchestration transaction."""

from __future__ import annotations

from . import face_anim


def _manager():
    from .features_api import feature_manager

    return feature_manager


def play(payload):
    # File/null previews have no physical resource to coordinate.
    sink = payload.get("sink", face_anim.DEFAULT_SINK) if isinstance(payload, dict) else None
    if sink != "lcd":
        return face_anim.play(payload)
    with _manager().transaction():

        def prepare():
            result = _manager().service_action("lcd-renderer.service", "stop")
            if not result.get("ok"):
                raise RuntimeError("lcd_owner_release_failed")

        return face_anim.play(payload, prepare_lcd=prepare)


def stop(payload=None):
    with _manager().transaction():
        return face_anim.stop(payload)


def command(payload):
    with _manager().transaction():
        return face_anim.command(payload)
