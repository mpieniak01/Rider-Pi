"""Registration and audio cleanup for the optional Venom integration endpoints."""

from . import agent_control_api, compute_api, navigation_api, playback_api


def register_control_audio(app):
    agent_control_api.register(app)
    playback_api.register(app)


def register_compute(app):
    app.add_url_rule(
        "/api/navigation/status",
        endpoint="navigation_loop_status",
        view_func=navigation_api.status_handler,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/navigation/config",
        endpoint="navigation_loop_config",
        view_func=navigation_api.config_handler,
        methods=["GET", "POST"],
    )
    app.add_url_rule("/api/compute/config", view_func=compute_api.config_handler, methods=["GET", "POST", "OPTIONS"])
    app.add_url_rule("/api/compute/status", view_func=compute_api.status_handler, methods=["GET"])
    app.add_url_rule("/api/compute/tasks/<task>", view_func=compute_api.task_handler, methods=["POST"])


def close(app):
    playback_api.close(app)
