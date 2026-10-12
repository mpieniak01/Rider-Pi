"""Emergency in-process transport: the same handlers and contracts as HTTP.

No socket server, subscriber or daemon starts. Use --direct locally when the
web API is stopped; the verified passive journal survives the API restart.
"""

from __future__ import annotations

import json

from common.api_client import APIClient, APIError


class LocalAPIClient(APIClient):
    def __init__(self, base_url=None):
        if base_url is not None:
            raise ValueError("direct_mode_is_local_only")
        from flask import Flask

        from services.api_core import face_studio, features_api, resource_api, services_api
        from services.api_core.http_contract import install
        from services.api_core.service_logs import service_logs

        self.app = Flask("rider-local-control")
        self.app.add_url_rule("/api/logic/catalog", view_func=features_api.feature_catalog_handler)
        self.app.add_url_rule("/api/logic/feature/<name>", view_func=features_api.feature_handler, methods=["POST"])
        self.app.add_url_rule("/svc/<name>", "service_status", services_api.svc_status)
        self.app.add_url_rule("/svc/<name>", "service_action", services_api.svc_action, methods=["POST"])
        self.app.add_url_rule("/api/resource/<name>", view_func=resource_api.api_resource, methods=["GET", "POST"])
        self.app.add_url_rule("/api/services/<unit>/logs", view_func=service_logs)
        face_studio.register(self.app)
        install(self.app, after_request=True)

    def request(self, path, method="GET", body=None):
        import sys
        from io import BytesIO

        from common.api_client import ACCEPT

        encoded = json.dumps(body, allow_nan=False).encode() if body is not None else b""
        with self.app.request_context(
            {
                "wsgi.url_scheme": "http",
                "SERVER_NAME": "localhost",
                "SERVER_PORT": "80",
                "REQUEST_METHOD": method,
                "PATH_INFO": path.split("?", 1)[0],
                "QUERY_STRING": path.partition("?")[2],
                "CONTENT_TYPE": "application/json" if body is not None else "",
                "CONTENT_LENGTH": str(len(encoded)),
                "wsgi.input": BytesIO(encoded),
                "wsgi.errors": sys.stderr,
                "wsgi.version": (1, 0),
                "HTTP_ACCEPT": ACCEPT,
            }
        ):
            response = self.app.full_dispatch_request()
            payload = json.loads(response.get_data())
            if response.status_code >= 400:
                error = payload.get("error") or {}
                raise APIError(error.get("code", "local_control_rejected"), response=payload)
            return payload
