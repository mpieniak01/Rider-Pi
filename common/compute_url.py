"""Private compute URL policy; LAN is an explicit, identity-pinned opt-in."""

from __future__ import annotations

import re
from ipaddress import ip_address
from urllib.parse import urlsplit

PEER_ID = re.compile(r"^[0-9a-f]{32}$")


def transport_options(selection):
    """Preserve existing factory signatures for the default secure profile."""
    if selection.get("transport_profile", "secure") == "secure" and not selection.get("expected_peer_id"):
        return {}
    return {
        "transport_profile": selection.get("transport_profile", "secure"),
        "expected_peer_id": selection.get("expected_peer_id"),
    }


def validate_transport_profile(transport_profile="secure", expected_peer_id=None):
    if not isinstance(transport_profile, str) or transport_profile not in {"secure", "trusted_lan"}:
        raise ValueError("invalid_transport_profile")
    if expected_peer_id is not None and (
        not isinstance(expected_peer_id, str) or not PEER_ID.fullmatch(expected_peer_id)
    ):
        raise ValueError("invalid_expected_peer_id")
    if transport_profile == "trusted_lan" and expected_peer_id is None:
        raise ValueError("transport_expected_peer_id_required")


def validate_compute_url(
    value: str, *, allow_api_path: bool = False, transport_profile="secure", expected_peer_id=None
):
    """Validate without DNS; remote HTTP requires an explicitly paired LAN peer."""
    validate_transport_profile(transport_profile, expected_peer_id)
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or "\\" in value
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError('invalid_compute_url')
    try:
        parsed = urlsplit(value)
        port = parsed.port
        host = parsed.hostname
    except ValueError:
        raise ValueError('invalid_compute_url') from None
    paths = {'', '/', '/api/v1/rider/compute'} if allow_api_path else {'', '/'}
    if (
        parsed.scheme not in {'http', 'https'}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.netloc.endswith(":")
        or parsed.path.rstrip('/') not in paths
        or port is not None
        and not 1 <= port <= 65535
    ):
        raise ValueError('invalid_compute_url')
    loopback = host.lower() == 'localhost'
    if not loopback:
        try:
            address = ip_address(host)
            loopback = address.is_loopback
        except ValueError:
            pass
    if parsed.scheme == 'http' and not loopback and transport_profile != 'trusted_lan':
        raise ValueError('compute_https_or_loopback_required')
    return parsed
