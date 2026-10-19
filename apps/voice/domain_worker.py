"""Voice HTTP worker: only selected domains admit requests and load backends."""

from __future__ import annotations

import ipaddress
import json
import os
import sys
import threading

from flask import Flask, g, jsonify, request

from apps.voice.domain_profiles import availability, requested_domains, worker_bind
from apps.voice.profile_state import write_status
from common.task_runtime import read_status
from services.api_core.http_security import install as install_http_security

_CHAT_ENDPOINT_INVALID = "chat_worker_endpoint_requires_loopback_bind"


def _chat_endpoint():
    """Advertise only the same-host worker, never an operator-supplied remote URL."""
    host, port = worker_bind()
    if host in {"0.0.0.0", "localhost"}:
        host = "127.0.0.1"
    elif host in {"::", "[::]"}:
        host = "::1"
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError as exc:
        raise ValueError(_CHAT_ENDPOINT_INVALID) from exc
    if not address.is_loopback or "%" in host or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError(_CHAT_ENDPOINT_INVALID)
    authority = f"[{address}]" if address.version == 6 else str(address)
    return f"http://{authority}:{port}/api/chat"


def _add_chat_endpoint(status, domains):
    if "chat" not in domains:
        return
    try:
        status["chat_endpoint"] = _chat_endpoint()
    except ValueError:
        status["capabilities"]["chat"]["ready"] = False
        status["missing"].append(_CHAT_ENDPOINT_INVALID)
        status["ready"] = False


def _load_profile_model(legacy, status, domain, importer, model_loader):
    capability = status["capabilities"][domain]
    capability["model_loaded"] = False
    if capability["ready"]:
        try:
            if not getattr(legacy, importer)():
                raise ImportError("selected backend unavailable")
            if getattr(legacy, model_loader)() is None:
                raise RuntimeError("selected model unavailable")
            capability["model_loaded"] = True
        except Exception as exc:
            status["missing"].append(f"{domain}_model_load_failed:{type(exc).__name__}")
            capability["ready"] = False


def update_profile(legacy, domains: set[str]) -> dict:
    status = availability(domains)
    _add_chat_endpoint(status, domains)
    for domain, importer, model_loader in (
        ("asr", "_load_vosk_backend", "_get_local_vosk_model"),
        ("tts", "_load_piper_backend", "_get_local_piper_voice"),
    ):
        if domain not in domains:
            continue
        _load_profile_model(legacy, status, domain, importer, model_loader)
    if "asr" not in domains:
        legacy._local_vosk_model = None
    if "tts" not in domains:
        legacy._local_piper_voice = None
    status["ready"] = bool(domains) and not status["missing"]
    write_status(status)
    return status


def _observed_profile(domains, profile_status):
    status = availability(domains)
    observed = profile_status()
    capabilities = observed.get("capabilities", {})
    confirmed = (
        observed.get("stale") is not True
        and isinstance(capabilities, dict)
        and all(
            isinstance(capabilities.get(domain), dict)
            and capabilities[domain].get("ready") is True
            and (domain == "chat" or capabilities[domain].get("model_loaded") is True)
            for domain in domains
        )
    )
    return {**status, "ready": status["ready"] and confirmed, "worker": observed}


def _admit_tts_payload(legacy):
    # The legacy handler accepts JSON independently of Content-Type.
    # Resolve exactly its configured default before admitting text.
    payload = request.get_json(force=True, silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "invalid_tts_payload"}), 400
    legacy._load_config()
    configured = getattr(getattr(getattr(g, "config", None), "tts", None), "backend", "")
    backend = payload.get("backend") or payload.get("provider") or payload.get("tts") or configured
    if not isinstance(backend, str) or backend.strip().lower() not in {"local", "piper"}:
        return jsonify({"ok": False, "error": "selected_profile_is_local_tts"}), 400


def _admit_domain(legacy, observed_profile):
    if request.path == "/healthz":
        return None
    domain = "asr" if request.path == "/api/asr" else "chat" if request.path == "/api/chat" else "tts"
    domains = requested_domains()
    if domain not in domains:
        return jsonify({"ok": False, "error": "voice_domain_inactive", "domain": domain}), 503
    if domain == "tts" and request.method == "POST":
        rejected = _admit_tts_payload(legacy)
        if rejected is not None:
            return rejected
    status = observed_profile({domain})
    if not status["ready"]:
        return jsonify({"ok": False, "error": "voice_backend_unavailable", **status}), 503
    legacy._load_config()
    return None


def create_app(legacy=None, profile_status=None) -> Flask:
    if legacy is None:
        os.environ.setdefault("VOICE_WEB_LOAD_PROFILE", "0")
        from apps.voice import web

        legacy = web
    app = Flask(__name__)
    install_http_security(app)
    profile_status = profile_status or (lambda: read_status("rider-voice-web.service"))

    def observed_profile(domains):
        return _observed_profile(domains, profile_status)

    @app.before_request
    def admit_domain():
        return _admit_domain(legacy, observed_profile)

    @app.route("/healthz", methods=["GET"])
    def health():
        status = observed_profile(requested_domains())
        return jsonify({"ok": status["ready"], **status}), 200 if status["ready"] else 503

    app.add_url_rule("/api/asr", endpoint="asr", view_func=legacy.api_asr, methods=["POST"])
    app.add_url_rule("/api/tts", endpoint="tts", view_func=legacy.api_tts, methods=["POST"])
    app.add_url_rule("/api/tts-test", endpoint="tts_test", view_func=legacy.api_tts_test, methods=["GET"])
    app.add_url_rule("/api/chat", endpoint="chat", view_func=legacy.api_chat_local, methods=["POST"])
    return app


def observe_profiles(legacy, stop) -> None:
    """Retry bounded heartbeat writes; stale data keeps admission unavailable."""
    while not stop.wait(0.5):
        try:
            update_profile(legacy, requested_domains())
        except Exception as exc:
            print(
                json.dumps({"ok": False, "error": "voice_profile_heartbeat_failed", "type": type(exc).__name__}),
                file=sys.stderr,
            )


def main() -> int:
    domains = requested_domains()
    status = availability(domains)
    _add_chat_endpoint(status, domains)
    if not status["ready"]:
        print(json.dumps({"ok": False, "error": "voice_profile_unavailable", **status}), file=sys.stderr)
        return 3
    if "--check" in sys.argv:
        print(json.dumps(status))
        return 0
    os.environ.setdefault("VOICE_WEB_LOAD_PROFILE", "0")
    from apps.voice import web

    profile = update_profile(web, requested_domains())
    if not profile["ready"]:
        print(json.dumps({"ok": False, "error": "voice_profile_unavailable", **profile}), file=sys.stderr)
        return 3
    stop = threading.Event()

    worker = threading.Thread(target=observe_profiles, args=(web, stop), name="voice-profile", daemon=True)
    worker.start()
    host, port = worker_bind()
    try:
        create_app(web).run(host=host, port=port)
    finally:
        stop.set()
        worker.join(timeout=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
