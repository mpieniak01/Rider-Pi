"""Private compute tokens travel over verified HTTPS or local tunnel endpoints."""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit


def validate_compute_url(value: str, *, allow_api_path: bool = False):
    """Validate without DNS: plain HTTP is allowed only on literal loopback.

    localhost is the only hostname exception. Other names resolving locally
    still require HTTPS; address changes must never expose a Bearer token.
    """
    if not isinstance(value, str) or not value or len(value) > 2048:
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
    if parsed.scheme == 'http' and not loopback:
        raise ValueError('compute_https_or_loopback_required')
    return parsed
