"""Service graph uses the same cached observation as tasks and /svc."""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

from flask import Blueprint, jsonify

from common import systemd_ctrl
from common.service_catalog import CONTRACT_VERSION

from .network_state import get_wifi_state
from .service_meta import SERVICE_META, UNIT_BY_ID

bp = Blueprint("services_dashboard", __name__, url_prefix="/api/services")


def _parse_systemctl(output: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def _status_from_active(active: str) -> str:
    return active if active in {"active", "inactive", "failed"} else "unknown"


def _systemd_state(unit: str) -> dict[str, Any]:
    from .features_api import feature_manager

    row = systemd_ctrl.status(unit)
    dependencies = sorted(set(row.get("wants", []) + row.get("requires", [])))
    return {
        **SERVICE_META[unit],
        **row,
        "unit": unit,
        "host": "pi",
        "status": "unknown" if row.get("error") else _status_from_active(row.get("active", "")),
        "active_state": row.get("active"),
        "sub_state": row.get("sub"),
        "load_state": row.get("load"),
        "unit_file_state": row.get("enabled"),
        "systemd_description": row.get("desc"),
        "actions": ["start", "stop", "restart", "enable", "disable"],
        "motion_owner": SERVICE_META[unit]["motion_owner"],
        "consumers": feature_manager.unit_consumers(unit),
        "dependencies": dependencies,
        "edges_out": [SERVICE_META[dependency]["id"] for dependency in dependencies if dependency in SERVICE_META],
    }


def _build_edges(edges: Iterable[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"from": src, "to": dst} for src, dst in sorted(set(edges))]


@bp.route("/graph", methods=["GET"])
def services_graph() -> Any:
    nodes = [_systemd_state(unit) for unit in SERVICE_META]
    edges = [(node["id"], target) for node in nodes for target in node["edges_out"] if target in UNIT_BY_ID]
    return jsonify(
        {
            "contract_version": CONTRACT_VERSION,
            "schema_version": CONTRACT_VERSION,
            "catalog_version": CONTRACT_VERSION,
            "host": "pi",
            "source": "pi",
            "observed_at": min((row["observed_at"] for row in nodes), default=time.time()),
            "stale": any(row.get("stale") for row in nodes),
            "nodes": nodes,
            "edges": _build_edges(edges),
            "generated_at": time.time(),
            "network": {"wifi": get_wifi_state()},
        }
    )


__all__ = ["bp", "services_graph"]
