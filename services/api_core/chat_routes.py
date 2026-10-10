"""Register chat handlers and the legacy store fallback on the current app."""

from typing import Any

from flask import jsonify, make_response, request

from services.api_core import chat_api


def register_chat_endpoints(app, add_rule, corsify) -> None:
    try:
        if hasattr(chat_api, "register"):
            chat_api.register(app)
            app.logger.info("[chat] blueprint/handlers registered via chat_api.register(app)")
    except Exception as e:
        app.logger.warning("[chat] register(app) failed: %s", e)

    rules_now = {r.rule for r in app.url_map.iter_rules()}
    need_history = "/api/chat/history" not in rules_now
    need_send = "/api/chat/send" not in rules_now
    need_ping = "/api/chat/ping" not in rules_now
    if not (need_history or need_send or need_ping):
        return

    try:
        from services.api_core import chat_store as _chat_store  # type: ignore
    except Exception as e:
        _chat_store = None  # type: ignore
        app.logger.warning("[chat] chat_store import failed: %s", e)

    def _ok(data: dict[str, Any], code: int = 200):
        return corsify(jsonify({"ok": True, **data})), code

    def _err(msg: str, code: int = 400):
        return corsify(jsonify({"ok": False, "error": msg})), code

    if need_ping:

        def _chat_ping():
            if request.method == "OPTIONS":
                return corsify(make_response("", 204))
            return _ok({"service": "chat", "mode": "fallback"})

        add_rule("/api/chat/ping", view_func=_chat_ping, methods=["GET", "OPTIONS"])

    if need_history:

        def _chat_history():
            if request.method == "OPTIONS":
                return corsify(make_response("", 204))
            limit = request.args.get("limit")
            try:
                n = int(limit) if limit is not None else None
            except Exception:
                n = None
            try:
                if _chat_store and hasattr(_chat_store, "history"):
                    items = list(_chat_store.history(n))  # type: ignore[attr-defined]
                elif _chat_store and hasattr(_chat_store, "get_store"):
                    items = _chat_store.get_store().list(limit=n)  # type: ignore[call-arg]
                else:
                    items = []
                return _ok({"items": items})
            except Exception as e:
                return _err(f"history_failed: {e}", 500)

        add_rule("/api/chat/history", view_func=_chat_history, methods=["GET", "OPTIONS"])

    if need_send:

        def _chat_send():
            if request.method == "OPTIONS":
                return corsify(make_response("", 204))
            payload = request.get_json(silent=True) or {}
            msg = (payload.get("msg") or "").strip()
            user = (payload.get("user") or "web").strip()
            if not msg:
                return _err("empty_msg", 400)
            try:
                if _chat_store and hasattr(_chat_store, "append"):
                    item = _chat_store.append({"msg": msg, "user": user})  # type: ignore[attr-defined]
                elif _chat_store and hasattr(_chat_store, "get_store"):
                    item = _chat_store.get_store().add(msg=msg, user=user)  # type: ignore[attr-defined]
                else:
                    item = {"msg": msg, "user": user}
                return _ok({"item": item})
            except Exception as e:
                return _err(f"send_failed: {e}", 500)

        add_rule("/api/chat/send", view_func=_chat_send, methods=["POST", "OPTIONS"])

    app.logger.info(
        "[chat] fallback endpoints active: "
        f"{'history ' if need_history else ''}"
        f"{'send ' if need_send else ''}"
        f"{'ping' if need_ping else ''}".strip()
    )
