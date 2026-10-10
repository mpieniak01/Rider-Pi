"""Resolve the selected text profile from its actual worker heartbeat."""

from __future__ import annotations

from urllib.parse import urlparse

from apps.voice.domain_profiles import requested_domains
from common import systemd_ctrl, task_runtime


def selected_endpoint() -> str | None:
    if "chat" not in requested_domains():
        return None
    unit = "rider-voice-web.service"
    status = task_runtime.read_status(unit)
    capabilities = status.get("capabilities")
    capability = capabilities.get("chat") if isinstance(capabilities, dict) else None
    if not isinstance(capability, dict):
        return None
    domains = status.get("domains")
    if (
        status.get("stale") is True
        or capability.get("ready") is not True
        or not isinstance(domains, list)
        or "chat" not in domains
    ):
        return None
    observed = systemd_ctrl.status(unit)
    pid = observed.get("pid")
    if (
        observed.get("error")
        or observed.get("active") != "active"
        or isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or status.get("pid") != pid
    ):
        return None
    endpoint = status.get("chat_endpoint")
    if not isinstance(endpoint, str):
        return None
    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return None
    if parsed.scheme != "http" or parsed.path != "/api/chat" or not parsed.hostname or parsed.username:
        return None
    return endpoint
