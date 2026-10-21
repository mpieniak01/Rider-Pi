"""One-off Pi API computation uses the same client as media goals and the CLI."""

import threading
import time
import uuid

from apps.compute.client import ComputeClient, ComputeError
from apps.compute.runners import device_session
from common.compute_url import transport_options
from services import compute_config

_panel_lock = threading.Lock()


def execute(task, payload, content_type, params=None, *, client_factory=ComputeClient):
    if task == 'conversation.respond':
        raise ComputeError('conversation_voice_only', 403)
    selected = compute_config.selected_executor()
    if selected is None:
        raise ComputeError("compute_executor_not_selected", 503)
    if task not in selected["tasks"]:
        raise ComputeError("compute_task_not_selected", 400)
    if not _panel_lock.acquire(blocking=False):
        raise ComputeError("compute_saturated", 429)
    client = None
    try:
        client = client_factory(
            selected["url"],
            selected["device_id"],
            selected["token"],
            device_session(),
            selected["id"],
            client_id="panel",
            **transport_options(selected),
        )
        job = client.submit(
            task,
            payload,
            content_type,
            {
                "captured_at": time.time(),
                "input_id": uuid.uuid4().hex,
                "stream_id": "panel",
                "sequence": 1,
                "ttl_ms": 60000,
                "timestamp_source": "operator_input",
            },
            params=params,
        )
        result = client.result(job, timeout=60)
        if compute_config.snapshot()["revision"] != selected["revision"]:
            raise ComputeError("compute_selection_changed", 409)
        binary = client.output(job) if result.get("output_available") else None
        compute_config.record_status("panel", result, revision=selected["revision"])
        return result, binary
    finally:
        if client is not None:
            client.close()
        _panel_lock.release()
