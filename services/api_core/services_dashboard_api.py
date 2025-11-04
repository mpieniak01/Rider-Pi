from __future__ import annotations

import subprocess
import time
from collections.abc import Iterable
from typing import Any

from flask import Blueprint, jsonify

from .service_meta import SERVICE_META, UNIT_BY_ID

bp = Blueprint("services_dashboard", __name__, url_prefix="/api/services")

_SYSTEMCTL_ARGS = [
    "--no-page",
    "--property=Id,ActiveState,SubState,Description,ActiveEnterTimestamp",
]


def _parse_systemctl(output: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def _status_from_active(active: str) -> str:
    normalized = (active or "").strip().lower()
    if normalized in {"active", "inactive", "failed"}:
        return normalized
    return "unknown"


def _systemd_state(unit: str) -> dict[str, Any]:
    meta = SERVICE_META[unit]
    payload: dict[str, Any] = {
        "unit": unit,
        "id": meta["id"],
        "group": meta["group"],
        "label": meta["label"],
        "description": meta["description"],
        "edges_out": list(meta["edges_out"]),
    }
    try:
        output = subprocess.check_output(
            ["systemctl", "show", unit, *_SYSTEMCTL_ARGS],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=3.0,
        )
    except subprocess.CalledProcessError as exc:
        payload.update(
            {
                "status": "unknown",
                "active_state": None,
                "sub_state": None,
                "since": None,
                "systemd_description": None,
                "error": (exc.output or str(exc)).strip(),
            }
        )
        return payload
    except Exception as exc:  # pragma: no cover - defensive catch
        payload.update(
            {
                "status": "unknown",
                "active_state": None,
                "sub_state": None,
                "since": None,
                "systemd_description": None,
                "error": str(exc),
            }
        )
        return payload

    data = _parse_systemctl(output)
    active_state = data.get("ActiveState", "").strip().lower() or None
    sub_state = data.get("SubState", "").strip().lower() or None
    status = _status_from_active(data.get("ActiveState", ""))
    since_raw = data.get("ActiveEnterTimestamp", "")
    since = since_raw.strip() if since_raw and since_raw.strip().lower() not in {"", "n/a"} else None

    payload.update(
        {
            "status": status,
            "active_state": active_state,
            "sub_state": sub_state,
            "since": since,
            "systemd_description": data.get("Description"),
        }
    )
    return payload


def _build_edges(edges: Iterable[tuple[str, str]]) -> list[dict[str, str]]:
    unique: set[tuple[str, str]] = set(edges)
    return [{"from": src, "to": dst} for src, dst in sorted(unique)]


@bp.get("/graph")
def services_graph() -> Any:
    nodes = []
    edges: list[tuple[str, str]] = []
    for unit, meta in SERVICE_META.items():
        node = _systemd_state(unit)
        nodes.append(node)
        for target in meta["edges_out"]:
            if target in UNIT_BY_ID:
                edges.append((meta["id"], target))
    payload = {
        "nodes": nodes,
        "edges": _build_edges(edges),
        "generated_at": time.time(),
    }
    return jsonify(payload)


__all__ = ["bp", "services_graph"]
