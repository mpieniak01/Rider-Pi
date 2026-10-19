"""Resolve the selected text profile from its actual worker heartbeat."""

from __future__ import annotations

import ipaddress
import logging
from urllib.parse import urlparse

from apps.voice.domain_profiles import requested_domains
from common import systemd_ctrl, task_runtime

_LOGGER = logging.getLogger(__name__)


def _is_loopback_worker_endpoint(endpoint) -> bool:
    if not isinstance(endpoint, str):
        return False
    try:
        parsed = urlparse(endpoint)
        host, port = parsed.hostname, parsed.port
        address = ipaddress.ip_address(host) if host else None
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.path == "/api/chat"
        and address is not None
        and address.is_loopback
        and "%" not in host
        and type(port) is int
        and 1 <= port <= 65535
        and parsed.username is None
        and parsed.password is None
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


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
    if not _is_loopback_worker_endpoint(endpoint):
        _LOGGER.warning("Selected voice worker endpoint rejected: expected loopback HTTP /api/chat with explicit port")
        return None
    return endpoint
