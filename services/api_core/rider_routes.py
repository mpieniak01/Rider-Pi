"""Registration and audio cleanup for the optional Venom integration endpoints."""

from . import agent_control_api, camera_pipeline_api, compute_api, navigation_api, playback_api, transport_api


def register_control_audio(app):
    agent_control_api.register(app)
    playback_api.register(app)


def register_compute(app):
    transport_api.register(app)
    camera_pipeline_api.register(app)
    app.add_url_rule(
        "/api/navigation/trial",
        endpoint="navigation_trial_start",
        view_func=navigation_api.trial_handler,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/navigation/journey",
        endpoint="navigation_journey_start",
        view_func=navigation_api.journey_handler,
        methods=["POST"],
    )
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
    app.add_url_rule("/api/navigation/local-models", view_func=navigation_api.local_models_handler, methods=["GET"])
    app.add_url_rule("/api/navigation/models", view_func=navigation_api.models_handler, methods=["GET"])
    app.add_url_rule("/api/navigation/model", view_func=navigation_api.model_handler, methods=["POST"])
    app.add_url_rule(
        "/api/navigation/model-selection", view_func=navigation_api.model_selection_handler, methods=["POST"]
    )
    app.add_url_rule("/api/compute/config", view_func=compute_api.config_handler, methods=["GET", "POST", "OPTIONS"])
    app.add_url_rule("/api/compute/status", view_func=compute_api.status_handler, methods=["GET"])
    app.add_url_rule("/api/compute/tasks/<task>", view_func=compute_api.task_handler, methods=["POST"])


def close(app):
    playback_api.close(app)
