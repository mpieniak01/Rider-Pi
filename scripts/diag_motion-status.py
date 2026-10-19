#!/usr/bin/env python3
"""Read-only observation. No SDK, UART, service start or arming."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from urllib.parse import urlsplit, urlunsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("diagnostic_redirect_not_allowed")


def diagnostic_base(value):
    parsed = urlsplit(value if "://" in value else "//" + value)
    allowed = {host.strip() for host in os.getenv("RIDER_DIAGNOSTIC_HOSTS", "localhost,127.0.0.1,::1").split(",")}
    ports = {int(port) for port in os.getenv("RIDER_DIAGNOSTIC_PORTS", "8080,8081,443").split(",")}
    scheme = parsed.scheme or "http"
    port = parsed.port or (443 if scheme == "https" else 80)
    if (
        scheme not in {"http", "https"}
        or parsed.hostname not in allowed
        or port not in ports
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("diagnostic_target_not_allowed")
    return urlunsplit((scheme, parsed.netloc, "", "", ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("api", nargs="?", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    base = diagnostic_base(args.api)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for path in ("/healthz", "/api/version", "/api/control/state", "/api/devices"):
        with opener.open(base + path, timeout=3) as response:
            body = json.load(response)
        print(json.dumps({"path": path, "observation": body}, ensure_ascii=False))


if __name__ == "__main__":
    main()
