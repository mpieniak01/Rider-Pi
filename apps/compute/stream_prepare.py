"""Native stream demand handshake before acquiring any motion authority."""

from __future__ import annotations

import json
import time
import urllib.request

from apps.compute.client import ComputeError
from apps.compute.runners import selected_executor
from services.camera_pipeline_store import native


def prepare_stream(*, selection=None, timeout_s=2.0, opener=None, clock=time.monotonic, sleep=time.sleep):
    if not native():
        return None
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
        req = urllib.request.Request(
            base + "/vision/status?stream=true",
            headers={
                "X-Rider-Device": selection["device_id"],
                "Authorization": "Bearer " + selection["token"],
            },
        )
        with opener.open(req, timeout=min(0.5, max(0.01, deadline - clock()))) as response:
            body = response.read(16385)
            if len(body) > 16384:
                raise ComputeError("navigation_stream_status_bounds")
            status = json.loads(body)
        if (
            isinstance(status, dict)
            and isinstance(status.get("stream"), dict)
            and status["stream"].get("ready") is True
        ):
            return status["stream"]
        sleep(min(0.05, max(0, deadline - clock())))
    raise ComputeError("navigation_stream_prepare_timeout")
