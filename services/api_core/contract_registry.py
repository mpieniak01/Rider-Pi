"""HTTP domain declarations; service and task identities stay in their catalog."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Contract:
    name: str
    version: int = 1
    action: str | None = None


_GROUPS = {
    "rider.catalog": (2, ("/api/logic/catalog",)),
    "rider.tasks": (2, ("/api/logic/features", "/api/logic/state", "/api/logic/summary", "/api/logic/feature/<name>")),
    "rider.service_graph": (2, ("/api/services/graph",)),
    "rider.services": (2, ("/svc", "/svc/<name>", "/svc/<name>/status", "/api/services/<unit>/logs")),
    "rider.resources": (1, ("/api/resource/<name>",)),
    "rider.providers": (
        1,
        (
            "/api/providers/state",
            "/api/providers/health",
            "/api/providers/<domain>",
            "/api/providers/pc-heartbeat",
            "/api/system/ai-mode",
        ),
    ),
    "rider.models": (1, ("/api/models/installed",)),
    "rider.safety": (
        1,
        (
            "/api/safety",
            "/api/control/state",
            "/api/control",
            "/api/cmd",
            "/api/control_legacy",
            "/api/control/balance",
            "/api/control/height",
            "/api/motion/queue",
            "/api/flags",
            "/api/flags/<name>/<state>",
            "/api/stop",
        ),
    ),
    "rider.navigation": (
        1,
        (
            "/api/navigator/status",
            "/api/navigator/start",
            "/api/navigator/stop",
            "/api/navigator/config",
            "/api/navigator/return_home",
        ),
    ),
    "rider.odometry": (1, ("/api/odometry/state", "/api/odometry/reference")),
    "rider.calibration": (
        1,
        (
            "/api/calibration/state",
            "/api/calibration/controls",
            "/api/calibration/profiles",
            "/api/calibration/profiles/<digest>",
            "/api/calibration/activate",
        ),
    ),
    "rider.telemetry": (1, ("/state", "/api/devices")),
    "rider.system": (1, ("/sysinfo", "/api/metrics", "/api/status")),
    "rider.health": (1, ("/healthz", "/health", "/livez", "/readyz", "/api/bus/health")),
    "rider.api_metrics": (1, ("/api/app-metrics",)),
    "rider.face": (
        1,
        (
            "/face/ping",
            "/face/render",
            "/face/play",
            "/face/stop",
            "/face/state",
            "/api/draw/face",
            "/draw/face",
            "/api/face-studio/runtime",
            "/api/face-studio/runtime/play",
            "/api/face-studio/runtime/stop",
            "/api/face-studio/runtime/event",
            "/api/face-studio/runtime/frame",
        ),
    ),
    "rider.face_studio": (
        1,
        ("/api/face-studio/gestures", "/api/face-studio/gestures/<key>", "/api/face-studio/frame"),
    ),
    "rider.chat": (1, ("/api/chat", "/api/chat/ping", "/api/chat/history", "/api/chat/send")),
    "rider.home": (
        1,
        ("/api/home/auth/url", "/api/home/auth", "/api/home/status", "/api/home/devices", "/api/home/command"),
    ),
    "rider.google_feed": (1, ("/api/google/status", "/api/google/raw/last.json", "/raw/last.json")),
    "rider.version": (1, ("/api/status/version",)),
    "rider.voice": (
        1,
        (
            "/api/voice/capture",
            "/api/voice/say",
            "/api/voice/tts",
            "/api/voice/asr",
            "/api/voice/providers",
            "/api/voice/providers/test",
        ),
    ),
    "rider.frames": (
        1,
        (
            "/camera/raw",
            "/camera/proc",
            "/camera/last",
            "/camera/placeholder",
            "/api/last_frame",
            "/snapshots/<path:fname>",
        ),
    ),
}

CONTRACTS = {route: Contract(name, version) for name, (version, routes) in _GROUPS.items() for route in routes}
for _suffix in (
    "cam",
    "edge",
    "ssd",
    "obst",
    "tracker",
    "snap-info",
    "obstacle",
    "tracking/mode",
    "follow/face",
    "follow/hand",
):
    for _prefix in ("/vision/", "/api/vision/"):
        _family = (
            "rider.obstacle"
            if _suffix == "obstacle"
            else "rider.tasks"
            if _suffix in {"tracking/mode", "follow/face", "follow/hand"}
            else "rider.frames"
        )
        CONTRACTS[_prefix + _suffix] = Contract(_family, 2 if _family == "rider.tasks" else 1)


def contract_for(rule: str | None) -> Contract:
    if rule in {"/control", "/api/move", "/api/balance", "/api/height"}:
        return Contract("rider.safety")
    if rule == "/api/version":
        return Contract("rider.version")
    return CONTRACTS.get(rule or "", Contract("rider.http"))


def service_row(row: dict) -> dict:
    """One systemd shape for graph, /svc and task members; never infer readiness."""
    value = dict(row)
    unit = row.get("unit")
    host = row.get("host", "pi")
    value.update(
        identity=f"{host}:{unit}" if unit else None,
        active_state=row.get("active_state", row.get("active") if isinstance(row.get("active"), str) else None),
        sub_state=row.get("sub_state", row.get("sub")),
        load_state=row.get("load_state", row.get("load")),
        unit_file_state=row.get("unit_file_state", row.get("enabled")),
    )
    if type(row.get("process_running")) is bool:
        value["process_running"] = row["process_running"]
    elif type(row.get("pid")) is int:
        value["process_running"] = row["pid"] > 0 and value["active_state"] == "active"
    else:
        value["process_running"] = None
    value.setdefault("installed", value["load_state"] == "loaded" if value["load_state"] is not None else None)
    value.setdefault("ready", None)
    if "edges_out" in row:
        from common.service_catalog import UNIT_CATALOG

        identities = {meta["id"]: f"{host}:{name}" for name, meta in UNIT_CATALOG.items()}
        value["edges_out"] = [identities.get(target, target) for target in row["edges_out"]]
    for key in ("active", "sub", "load", "enabled"):
        value.pop(key, None)
    return value


def projection(rule: str | None, payload):
    """Produce a single canonical domain payload, preserving legacy response defaults."""
    if not isinstance(payload, dict):
        return payload
    data = {key: value for key, value in payload.items() if key not in {"ok", "http_status", "_http_status"}}
    if rule in {"/svc/<name>", "/svc/<name>/status"} and "unit" in data:
        data = service_row(data)
    if rule == "/svc":
        data["services"] = [service_row(row) for row in data.get("services", [])]
    if rule == "/api/services/graph":
        rows = data.get("nodes", [])
        identities = {row.get("id"): f"{row.get('host', 'pi')}:{row.get('unit')}" for row in rows}
        data["nodes"] = [{**service_row(row), "id": identities.get(row.get("id"))} for row in rows]
        data["edges"] = [
            {
                **edge,
                "from": identities.get(edge.get("from"), edge.get("from")),
                "to": identities.get(edge.get("to"), edge.get("to")),
            }
            for edge in data.get("edges", [])
        ]
    if rule and rule.startswith("/api/logic/"):
        # Only observed task members are systemd rows; static catalog units are definitions.
        def task(row):
            return {
                **row,
                "identity": f"{row.get('host', 'pi')}:{row.get('name')}",
                "services": [service_row(service) for service in row.get("services", [])],
            }

        if isinstance(data.get("features"), list):
            data["features"] = [task(row) for row in data["features"]]
        if isinstance(data.get("summary"), dict):
            data["summary"] = {
                **data["summary"],
                "features": [task(row) for row in data["summary"].get("features", [])],
            }
        if isinstance(data.get("state"), dict):
            data["state"] = {
                **data["state"],
                "features": [task(row) for row in data["state"].get("features", [])],
            }
        result = data.get("result")
        if isinstance(result, dict) and isinstance(result.get("task"), dict):
            data["result"] = {**result, "task": task(result["task"])}
    if rule in {"/state", "/healthz"}:
        try:
            from common.observations import canonical_telemetry_payload
        except ImportError:
            pass
        else:
            data = canonical_telemetry_payload(data)
    if rule and rule.startswith("/api/providers/") and "pc_health" in data:
        data["peer_health"] = data.pop("pc_health")
    if rule and rule.endswith("/vision/obstacle"):
        for old, new in (("edge_pct", "edge_ratio"), ("edge_pct_raw", "edge_ratio_raw")):
            if old in data:
                data[new] = data.pop(old)
        if isinstance(data.get("diag"), dict):
            data["diag"] = dict(data["diag"])
            if "edge_pct_raw" in data["diag"]:
                data["diag"]["edge_ratio_raw"] = data["diag"].pop("edge_pct_raw")
    return data
