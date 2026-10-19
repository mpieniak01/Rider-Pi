"""Google Home authentication route separated from app bootstrap."""

from flask import jsonify, make_response, request

from services.api_core import google_home_api
from services.api_core.google_home_api import build_auth_url_preview


def home_auth_url(corsify, _logger):
    if request.method == "OPTIONS":
        return corsify(make_response("", 204))
    preview = build_auth_url_preview()
    code = 200 if preview.get("ok") else 400
    return corsify(jsonify(preview)), code


def home_auth(corsify, logger):
    if request.method == "OPTIONS":
        return corsify(make_response("", 204))

    # log preview to journald (wrap lines for ruff)
    try:
        import json as _json
        import subprocess

        preview = build_auth_url_preview()
        if preview.get("ok"):
            auth_url = preview.get("auth_url", "")
            port = preview.get("port")

            cmd1 = [
                "/bin/sh",
                "-lc",
                (
                    "printf '%s' "
                    + _json.dumps("[google-oauth] auth_url: " + auth_url)
                    + " | systemd-cat -t rider-api-env -p info"
                ),
            ]
            subprocess.run(cmd1, check=False)

            if port:
                cmd2 = [
                    "/bin/sh",
                    "-lc",
                    (
                        "printf '%s' "
                        + _json.dumps("[google-oauth] loopback port: " + str(port))
                        + " | systemd-cat -t rider-api-env -p info"
                    ),
                ]
                subprocess.run(cmd2, check=False)
    except Exception as _e:
        logger.warning("auth preview log failed: %s", _e)

    try:
        result = google_home_api.start_oauth_flow()
        status_code = 200 if result.get("ok") else 500
        return corsify(jsonify(result)), status_code
    except Exception as e:
        logger.error("OAuth flow error: %s", e, exc_info=True)
        return corsify(jsonify({"ok": False, "error": "Authentication configuration error"})), 500
