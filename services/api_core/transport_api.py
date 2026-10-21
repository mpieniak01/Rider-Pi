"""Passive public identity; never starts media, inference or actuation."""

from flask import jsonify

from services.transport_identity import identity


def identity_handler():
    try:
        response = jsonify(identity())
    except (ValueError, OSError):
        return jsonify(error="transport_identity_unavailable"), 503
    response.headers["Cache-Control"] = "no-store"
    return response


def register(app):
    app.add_url_rule("/api/v1/transport/identity", view_func=identity_handler, methods=["GET"])
