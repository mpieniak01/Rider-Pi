"""Persistent installation identity, distinct from device and process sessions."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from common.compute_url import PEER_ID
from common.secure_files import atomic_write, readonly_file


def identity():
    path = Path(os.getenv("RIDER_TRANSPORT_IDENTITY_FILE", "data/transport_identity.json"))
    try:
        return _read(path)
    except FileNotFoundError:
        data = {"protocol_version": 1, "peer_id": uuid.uuid4().hex, "service_role": "rider_pi"}
        encoded = json.dumps(data, separators=(",", ":")).encode()
        try:
            atomic_write(path, lambda stream: _save(stream, encoded), replace=False)
        except FileExistsError:
            pass  # A concurrent API process owns the first complete identity.
        return _read(path)


def _save(stream, encoded):
    stream.write(encoded)
    stream.flush()
    os.fsync(stream.fileno())


def _read(path):
    with readonly_file(path) as stream:
        raw = stream.read(1025)
    try:
        data = json.loads(raw) if len(raw) <= 1024 else None
    except ValueError:
        data = None
    if (
        not isinstance(data, dict)
        or type(data.get("protocol_version")) is not int
        or data["protocol_version"] != 1
        or data.get("service_role") != "rider_pi"
        or not isinstance(data.get("peer_id"), str)
        or not PEER_ID.fullmatch(data["peer_id"])
    ):
        raise ValueError("transport_identity_invalid")
    return {key: data[key] for key in ("protocol_version", "peer_id", "service_role")}
