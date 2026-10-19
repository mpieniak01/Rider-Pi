"""Register chat handlers and the legacy store fallback on the current app."""

from typing import Any

from flask import jsonify, make_response, request

from services.api_core import chat_api


class _FallbackChat:
    def __init__(self, store, corsify):
        self.store = store
        self.corsify = corsify

    def _ok(self, data: dict[str, Any], code: int = 200):
        return self.corsify(jsonify({"ok": True, **data})), code

    def _err(self, msg: str, code: int = 400):
        return self.corsify(jsonify({"ok": False, "error": msg})), code

    def _chat_ping(self):
        if request.method == "OPTIONS":
            return self.corsify(make_response("", 204))
        return self._ok({"service": "chat", "mode": "fallback"})

    def _chat_history(self):
        if request.method == "OPTIONS":
            return self.corsify(make_response("", 204))
        limit = request.args.get("limit")
        try:
            n = int(limit) if limit is not None else None
        except Exception:
            n = None
        try:
            if self.store and hasattr(self.store, "history"):
                items = list(self.store.history(n))  # type: ignore[attr-defined]
            elif self.store and hasattr(self.store, "get_store"):
                items = self.store.get_store().list(limit=n)  # type: ignore[call-arg]
            else:
                items = []
            return self._ok({"items": items})
        except Exception as e:
            return self._err(f"history_failed: {e}", 500)

    def _chat_send(self):
        if request.method == "OPTIONS":
            return self.corsify(make_response("", 204))
        payload = request.get_json(silent=True) or {}
        msg = (payload.get("msg") or "").strip()
        user = (payload.get("user") or "web").strip()
        if not msg:
            return self._err("empty_msg", 400)
        try:
            if self.store and hasattr(self.store, "append"):
                item = self.store.append({"msg": msg, "user": user})  # type: ignore[attr-defined]
            elif self.store and hasattr(self.store, "get_store"):
                item = self.store.get_store().add(msg=msg, user=user)  # type: ignore[attr-defined]
            else:
                item = {"msg": msg, "user": user}
            return self._ok({"item": item})
        except Exception as e:
            return self._err(f"send_failed: {e}", 500)


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

    handlers = _FallbackChat(_chat_store, corsify)
    if need_ping:
        add_rule("/api/chat/ping", view_func=handlers._chat_ping, methods=["GET", "OPTIONS"])
    if need_history:
        add_rule("/api/chat/history", view_func=handlers._chat_history, methods=["GET", "OPTIONS"])
    if need_send:
        add_rule("/api/chat/send", view_func=handlers._chat_send, methods=["POST", "OPTIONS"])

    app.logger.info(
        "[chat] fallback endpoints active: "
        f"{'history ' if need_history else ''}"
        f"{'send ' if need_send else ''}"
        f"{'ping' if need_ping else ''}".strip()
    )
