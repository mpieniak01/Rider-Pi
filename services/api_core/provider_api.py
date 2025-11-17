"""Provider registry REST endpoints."""

from __future__ import annotations

from flask import Response, jsonify, make_response, request

from services import provider_registry as registry, provider_watchdog

provider_watchdog.ensure_started()


def _corsify(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, PATCH, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def providers_state_handler() -> tuple[Response, int]:
    snapshot = registry.get_state_snapshot()
    return _corsify(jsonify(snapshot)), 200


def providers_health_handler() -> tuple[Response, int]:
    health = registry.get_health_snapshot()
    return _corsify(jsonify({"pc_health": health})), 200


def providers_pc_heartbeat_handler() -> tuple[Response, int]:
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204)), 204

    payload = request.get_json(silent=True) or {}
    base_url = (payload.get("base_url") or "").strip()
    if not base_url:
        return _corsify(jsonify({"error": "base_url is required"})), 400

    reason = payload.get("reason") or "heartbeat"
    try:
        normalized = registry.set_pc_base_url(base_url, reason=reason)
    except ValueError as exc:
        return _corsify(jsonify({"error": str(exc)})), 400

    health_kwargs = {
        "reachable": True,
        "status": payload.get("status") or "online",
        "reason": reason,
    }
    if "latency_ms" in payload:
        health_kwargs["latency_ms"] = payload.get("latency_ms")
    registry.update_pc_health(**health_kwargs)

    return _corsify(jsonify({"ok": True, "base_url": normalized})), 200


def provider_domain_handler(domain: str) -> tuple[Response, int]:
    domain = (domain or "").lower()
    if domain not in registry.DOMAINS:
        return _corsify(jsonify({"error": f"Unknown domain: {domain}"})), 404

    if domain == "pc-heartbeat":
        if request.method == "OPTIONS":
            return _corsify(make_response("", 204)), 204
        if request.method == "POST":
            return providers_pc_heartbeat_handler()
        return _corsify(jsonify({"error": "Method not allowed"})), 405

    if request.method == "OPTIONS":
        return _corsify(make_response("", 204)), 204

    if request.method == "GET":
        state = registry.get_domain_state(domain)
        return _corsify(jsonify({"domain": domain, "state": state})), 200

    if request.method == "PATCH":
        payload = request.get_json(force=True, silent=True) or {}
        target = (payload.get("target") or "").strip().lower()
        reason = payload.get("reason") or "manual"

        if target not in ("local", "pc"):
            return _corsify(jsonify({"error": "target must be 'local' or 'pc'"})), 400

        try:
            state, changed = registry.set_domain_mode(domain, target, reason=reason)
        except ValueError as exc:
            return _corsify(jsonify({"error": str(exc)})), 400

        return (
            _corsify(
                jsonify(
                    {
                        "domain": domain,
                        "state": state,
                        "changed": changed,
                    }
                )
            ),
            200,
        )

    return _corsify(jsonify({"error": "Method not allowed"})), 405
