"""Small public CLI transport. Only the serving API owns orchestration state."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ACCEPT = "application/vnd.rider.api+json;version=1"


class APIError(RuntimeError):
    def __init__(self, message, *, response=None):
        super().__init__(message)
        self.response = response or {"ok": False, "error": message}


class APIClient:
    def __init__(self, base_url=None, *, opener=None):
        self.base = (base_url or os.getenv("RIDER_API_URL", "http://127.0.0.1:8080")).rstrip("/")
        url = urlsplit(self.base)
        if (
            url.scheme not in {"http", "https"}
            or not url.netloc
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("invalid_rider_api_url")
        self.open = opener or urlopen

    def request(self, path, method="GET", body=None):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("local_api_path_required")
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        headers = {"Accept": ACCEPT}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            response = self.open(request, timeout=30)
        except HTTPError as exc:
            response = exc
        except (URLError, OSError) as exc:
            raise APIError("rider_api_unavailable") from exc
        with response:
            try:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise APIError("rider_api_response_oversized")
                payload = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise APIError("invalid_rider_api_response") from exc
            code = response.status
            mime = response.headers.get("Content-Type", "").lower()
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if (
            not isinstance(meta, dict)
            or meta.get("envelope_version") != 1
            or mime.split(";", 1)[0].strip() != "application/vnd.rider.api+json"
            or "version=1" not in [part.strip() for part in mime.split(";")[1:]]
        ):
            raise APIError("unsupported_rider_api_contract")
        if code >= 400:
            error = payload.get("error") or {}
            message = error.get("code", "rider_api_rejected") if isinstance(error, dict) else str(error)
            raise APIError(message, response=payload)
        return payload

    def catalog(self):
        response = self.request("/api/logic/catalog")
        data, meta = response.get("data"), response.get("meta", {})
        if (
            not isinstance(data, dict)
            or meta.get("contract_id") != "rider.catalog"
            or meta.get("contract_version") != 2
        ):
            raise APIError("unsupported_rider_catalog")
        if data.get("catalog_version") != 2 or not isinstance(data.get("features"), list):
            raise APIError("unsupported_rider_catalog")
        return data
