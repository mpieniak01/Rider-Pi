# services/api_core/voice_local_proxy.py
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

from flask import Response, jsonify, make_response, request

# ──────────────────────────────────────────────────────────────────────────────
# Ustawienia
# ──────────────────────────────────────────────────────────────────────────────

VOICE_WEB_BASE = os.getenv("VOICE_WEB_BASE", "http://127.0.0.1:8092").rstrip("/")
HTTP_TIMEOUT = float(os.getenv("VOICE_HTTP_TIMEOUT", "45"))

# ──────────────────────────────────────────────────────────────────────────────
# CORS / preflight
# ──────────────────────────────────────────────────────────────────────────────


def _cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS,HEAD"
    return resp


def _preflight() -> Response:
    return _cors(make_response("", 204))


# ──────────────────────────────────────────────────────────────────────────────
# TTS: 8080 → (proxy) → 8092
# Stabilizujemy format: zawsze prosimy backend o JSON { audio_b64 }.
# Proxy dekoduje i oddaje 'audio/wav' (200) lub 502 z czytelnym błędem JSON.
# ──────────────────────────────────────────────────────────────────────────────
def tts_local_handler():
    if request.method == "OPTIONS":
        return _preflight()

    try:
        # 1) payload
        try:
            payload = request.get_json(force=True, silent=True) or {}
        except Exception:
            payload = {}

        # provider default → local (zachowujemy zgodność; backend i tak może to zignorować)
        provider = (payload.get("provider") or payload.get("backend") or "").lower()
        if provider not in ("local", "piper"):
            payload["provider"] = "local"

        # Przekaż ewentualne nadpisania (voice/model/format/backend)
        passthrough = {}
        for k in ("backend", "format", "voice", "model"):
            if k in payload:
                passthrough[k] = payload[k]
        # Tekst musi być; walidacja minimalna
        text = (payload.get("text") or "").strip()
        if not text:
            return _cors(jsonify({"ok": False, "error": "missing text"})), 400
        passthrough["text"] = text

        data = json.dumps(passthrough).encode("utf-8")

        # 2) prosimy backend o B64 (stabilny transport)
        url = f"{VOICE_WEB_BASE}/api/tts?b64=1"
        extra_qs = request.query_string.decode("utf-8", errors="ignore")
        if extra_qs:
            # jeżeli user podał query, dołączamy (np. voice=xxx); b64=1 zostaje
            url = f"{url}&{extra_qs}"

        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")

        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()

        # 3) JSON → dekodujemy do WAV
        if "application/json" in ctype:
            try:
                obj = json.loads(body.decode("utf-8", errors="ignore"))
            except Exception:
                return _cors(jsonify({"ok": False, "error": "invalid json from voice-web"})), 502

            if not obj or obj.get("status") != "ok" or "audio_b64" not in obj:
                # zwracamy błąd backendu dla łatwej diagnostyki
                return _cors(jsonify({"ok": False, "error": "tts failed", "backend": obj})), 502

            try:
                wav = base64.b64decode(obj["audio_b64"])
            except Exception as e:
                return _cors(jsonify({"ok": False, "error": f"b64 decode failed: {e}"})), 502

            r2 = Response(wav, status=200, mimetype="audio/wav")
            r2.headers["Content-Disposition"] = "inline; filename=tts.wav"
            r2.headers["X-Voice-Proxy"] = "local"
            return _cors(r2)

        # 4) Fallback – gdyby backend jednak zwrócił bezpośrednio WAV
        if "audio/wav" in ctype or "audio/x-wav" in ctype:
            r3 = Response(body, status=200, mimetype="audio/wav")
            r3.headers["Content-Disposition"] = "inline; filename=tts.wav"
            r3.headers["X-Voice-Proxy"] = "local"
            return _cors(r3)

        # 5) Inny typ → błąd
        return _cors(jsonify({"ok": False, "error": f"unexpected content-type from voice-web: {ctype}"})), 502

    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            err_body = ""
        return _cors(
            jsonify(
                {
                    "ok": False,
                    "error": f"voice tts http error: {e.code}",
                    "body": err_body[:800],
                }
            )
        ), 502
    except Exception as e:
        return _cors(jsonify({"ok": False, "error": f"voice tts proxy failed: {e}"})), 502


# ──────────────────────────────────────────────────────────────────────────────
# ASR: 8080 → (proxy) → 8092
# Wymagamy 'audio/wav' jako body. Przekazujemy 1:1 do backendu i zwracamy JSON.
# Gdy brak danych / zły Content-Type → 400.
# ──────────────────────────────────────────────────────────────────────────────
def asr_local_handler():
    if request.method == "OPTIONS":
        return _preflight()

    try:
        ctype = (request.headers.get("Content-Type") or "").lower()
        if "audio/wav" not in ctype and "audio/x-wav" not in ctype:
            return _cors(jsonify({"ok": False, "error": "expect audio/wav content-type"})), 400

        data = request.get_data(cache=False, as_text=False)
        if not data:
            return _cors(jsonify({"ok": False, "error": "no audio data"})), 400

        url = f"{VOICE_WEB_BASE}/api/asr"
        extra_qs = request.query_string.decode("utf-8", errors="ignore")
        if extra_qs:
            url = f"{url}?{extra_qs}"

        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "audio/wav")
        req.add_header("Accept", "application/json")

        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read()
            ctype_out = (resp.headers.get("Content-Type") or "").lower()
            status = resp.status

        if status != 200:
            # przekaż częściowo treść błędu backendu
            snippet = body.decode("utf-8", errors="ignore")[:800]
            return _cors(jsonify({"ok": False, "error": f"voice asr http error: {status}", "body": snippet})), 502

        if "application/json" not in ctype_out:
            return _cors(jsonify({"ok": False, "error": f"unexpected content-type: {ctype_out}"})), 502

        # prześlij JSON 1:1 (walidacja minimalna)
        try:
            obj = json.loads(body.decode("utf-8", errors="ignore"))
        except Exception:
            return _cors(jsonify({"ok": False, "error": "invalid json from voice-web"})), 502

        resp2 = jsonify(obj)
        resp2.headers["X-Voice-Proxy"] = "local"
        return _cors(resp2), 200

    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            err_body = ""
        return _cors(jsonify({"ok": False, "error": f"voice asr http error: {e.code}", "body": err_body[:800]})), 502
    except Exception as e:
        return _cors(jsonify({"ok": False, "error": f"voice asr proxy failed: {e}"})), 502
