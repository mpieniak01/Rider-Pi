"""HTTP projection of the shared, server-independent device controller."""

from __future__ import annotations

from flask import jsonify

from services.core import device_control


def manager():
    from .features_api import feature_manager

    return feature_manager


def led_status(name=None):
    return device_control.led_status(name)


def device_action(name, body):
    from . import face_anim

    result, status = device_control.action(manager(), name, body, face_runtime=face_anim)
    return jsonify(result), status
