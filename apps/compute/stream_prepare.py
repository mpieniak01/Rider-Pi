"""Native stream demand handshake before acquiring any motion authority."""

from __future__ import annotations

import contextlib
import json
import re
import socket
import time
import urllib.error
import urllib.request

from apps.compute.client import ComputeError
from apps.compute.runners import selected_executor
from services.camera_pipeline_store import native, snapshot


def http_error_code(error):
    """Only stable domain identifiers enter logs; never URLs, tokens or raw bodies."""
    fields = vars(error)
    cached = fields.get("rider_domain_code")
    if cached is not None:
        return cached
    code = "http_" + str(error.code)
    stream = fields.get("fp")
    if stream is None:
        fields["rider_domain_code"] = code
        return code
    try:
        body = stream.read(4097)
        payload = json.loads(body) if len(body) <= 4096 else {}
        detail = payload.get("detail", payload.get("error", {})) if isinstance(payload, dict) else {}
        candidate = detail.get("code") if isinstance(detail, dict) else detail
        if isinstance(candidate, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,95}", candidate):
            code = candidate
    except (OSError, ValueError, TypeError):
        pass
    finally:
        with contextlib.suppress(OSError):
            stream.close()
    fields["rider_domain_code"] = code
    return code


def _fresh_local_source(config, max_age_ms):
    from apps.camera.pipeline_ipc import read_frame

    try:
        item = read_frame(metadata_only=True)
        if item is None:
            return None
        source = item[1]
        captured = source.get("captured_monotonic_ns")
        if (
            source.get("pipeline_revision") != config["revision"]
            or type(captured) is not int
            or not 0 <= (time.monotonic_ns() - captured) / 1_000_000 < max_age_ms
            or not isinstance(source.get("camera_session"), str)
            or not source["camera_session"]
            or type(source.get("transport_epoch")) is not int
        ):
            return None
        return source
    except (OSError, ValueError, KeyError, TypeError):
        return None


def prepare_stream(
    *,
    selection=None,
    timeout_s=2.0,
    max_age_ms=300,
    opener=None,
    clock=time.monotonic,
    sleep=time.sleep,
):
    if not native():
        return None
    config = snapshot()
    selection = selection or selected_executor()
    if not selection:
        raise ComputeError("compute_executor_not_selected")
    if opener is None:
        from apps.compute.navigation import NoRedirect

        opener = urllib.request.build_opener(NoRedirect())
    base = selection["url"].rstrip("/")
    if not base.endswith("/api/v1/rider/compute"):
        base += "/api/v1/rider/compute"
    deadline = clock() + timeout_s
    while clock() < deadline:
        if snapshot() != config:
            raise ComputeError("navigation_configuration_changed", 409)
        local_source = _fresh_local_source(config, max_age_ms)
        if local_source is None:
            sleep(min(0.05, max(0, deadline - clock())))
            continue
        req = urllib.request.Request(
            base + "/vision/status?stream=true",
            headers={
                "X-Rider-Device": selection["device_id"],
                "Authorization": "Bearer " + selection["token"],
            },
        )
        remaining = deadline - clock()
        if remaining <= 0:
            break
        try:
            with opener.open(req, timeout=remaining) as response:
                # Header/connection time belongs to this same preparation budget.
                remaining = deadline - clock()
                if remaining <= 0:
                    raise ComputeError("navigation_stream_prepare_timeout", 504)
                raw = getattr(getattr(response, "fp", None), "raw", None)
                connection = getattr(raw, "_sock", None)
                if connection is not None:
                    connection.settimeout(remaining)
                body = response.read(16385)
                if len(body) > 16384:
                    raise ComputeError("navigation_stream_status_bounds")
                status = json.loads(body)
        except urllib.error.HTTPError as exc:
            raise ComputeError("navigation_stream_prepare_" + http_error_code(exc), exc.code) from None
        except (TimeoutError, socket.timeout):
            raise ComputeError("navigation_stream_prepare_timeout", 504) from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise ComputeError("navigation_stream_prepare_timeout", 504) from None
            raise
        if clock() >= deadline:
            break
        if snapshot() != config:
            raise ComputeError("navigation_configuration_changed", 409)
        if isinstance(status, dict) and isinstance(status.get("stream"), dict):
            stream = status["stream"]
            if stream.get("ready") is True:
                source = stream.get("latest_source")
                keys = ("camera_session", "transport_epoch", "pipeline_revision")
                if not isinstance(source, dict) or any(source.get(key) != local_source[key] for key in keys):
                    raise ComputeError("navigation_stream_source_mismatch", 409)
                captured = source.get("captured_monotonic_ns")
                if type(captured) is int and 0 <= (time.monotonic_ns() - captured) / 1_000_000 < max_age_ms:
                    return stream
        sleep(min(0.05, max(0, deadline - clock())))
    raise ComputeError("navigation_stream_prepare_timeout", 504)
