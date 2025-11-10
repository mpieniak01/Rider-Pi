# services/api_core/voice_local_proxy.py
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from flask import Response, jsonify, make_response, request

# ──────────────────────────────────────────────────────────────────────────────
# Ustawienia
# ──────────────────────────────────────────────────────────────────────────────

VOICE_WEB_BASE = os.getenv("VOICE_WEB_BASE", "http://127.0.0.1:8092").rstrip("/")
HTTP_TIMEOUT = float(os.getenv("VOICE_HTTP_TIMEOUT", "45"))
PROVIDER_TEST_TEXT = "To jest test TTS Rider-Pi."

try:
    from services.api_core import services_api
except Exception:  # pragma: no cover - opcjonalne w środowisku testowym
    services_api = None  # type: ignore


_PROVIDER_DEFS: list[dict[str, Any]] = [
    {
        "id": "local",
        "label": "Piper (lokalny)",
        "backend": "piper",
        "voice": "pl_PL-gosia-medium.onnx",
        "model": None,
        "description": "Offline TTS przez Piper na Rider-Pi.",
        "service": "voice-web",
    },
    {
        "id": "openai",
        "label": "OpenAI gpt-4o-mini-tts",
        "backend": "openai",
        "voice": "alloy",
        "model": "gpt-4o-mini-tts",
        "description": "Chmurowy TTS OpenAI (wymaga OPENAI_API_KEY).",
        "service": None,
    },
    {
        "id": "google",
        "label": "Google Gemini Kore",
        "backend": "google",
        "voice": "Kore",
        "model": "gemini-2.5-flash-preview-tts",
        "description": "Chmurowy TTS Gemini (wymaga GOOGLE_API_KEY).",
        "service": None,
    },
]

_PROVIDER_STATUS: dict[str, dict[str, Any]] = {}
_GOOGLE_ALLOWED_VOICES = {
    "achernar",
    "achird",
    "algenib",
    "algieba",
    "alnilam",
    "aoede",
    "autonoe",
    "callirrhoe",
    "charon",
    "despina",
    "enceladus",
    "erinome",
    "fenrir",
    "gacrux",
    "iapetus",
    "kore",
    "laomedeia",
    "leda",
    "orus",
    "puck",
    "pulcherrima",
    "rasalgethi",
    "sadachbia",
    "sadaltager",
    "schedar",
    "sulafat",
    "umbriel",
    "vindemiatrix",
    "zephyr",
    "zubenelgenubi",
}
_GOOGLE_DEFAULT_VOICE = "Kore"

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
# Provider metadata & diagnostics
# ──────────────────────────────────────────────────────────────────────────────


def _normalized_provider(entry: dict[str, Any]) -> dict[str, Any]:
    data = dict(entry)
    backend = (data.get("backend") or "").lower()
    if backend == "google":
        voice = (data.get("voice") or "").strip()
        if voice.lower() not in _GOOGLE_ALLOWED_VOICES:
            voice = _GOOGLE_DEFAULT_VOICE
        data["voice"] = voice
        data.setdefault("model", "gemini-2.5-flash-preview-tts")
    return data


def _provider_lookup(provider_id: str) -> dict[str, Any] | None:
    for entry in _PROVIDER_DEFS:
        if entry["id"] == provider_id:
            return _normalized_provider(entry)
    return None


def _provider_status_snapshot(provider_id: str) -> dict[str, Any]:
    status = _PROVIDER_STATUS.get(provider_id)
    if status is None:
        return {"state": "unknown", "detail": "nie testowano", "updated": None}
    return status


def _service_status(alias: str | None) -> dict[str, Any] | None:
    """
    Pobiera status jednostki systemd skojarzonej z providerem.
    Korzystamy z istniejących helperów services_api, jeśli są dostępne.
    """
    if not alias or services_api is None:
        return None
    try:
        unit = alias
        if hasattr(services_api, "_unit_for"):
            unit = services_api._unit_for(alias) or alias  # type: ignore[attr-defined]
        if not unit:
            return None
        if hasattr(services_api, "_svc_status"):
            status = services_api._svc_status(unit)  # type: ignore[attr-defined]
        else:  # pragma: no cover - awaryjnie spróbuj publicznej ścieżki HTTP
            status = {"unit": unit}
        status.setdefault("unit", unit)
        status.setdefault("alias", alias)
        return status
    except Exception as exc:  # pragma: no cover - diagnostyka
        return {"unit": alias, "alias": alias, "error": str(exc)}


def _probe_provider(entry: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    entry = _normalized_provider(entry)
    payload: dict[str, Any] = {
        "text": PROVIDER_TEST_TEXT,
        "backend": entry["backend"],
        "provider": entry.get("id"),
    }
    # voice/model opcjonalne – tylko gdy zdefiniowane
    if entry.get("voice"):
        payload["voice"] = entry["voice"]
    if entry.get("model"):
        payload["model"] = entry["model"]

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{VOICE_WEB_BASE}/api/tts?b64=1", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
            status_code = resp.status
    except urllib.error.HTTPError as e:
        latency_ms = int((time.time() - started) * 1000)
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            err_body = ""
        return {
            "id": entry["id"],
            "state": "error",
            "error": f"http {e.code}",
            "detail": err_body[:400],
            "latency_ms": latency_ms,
        }
    except Exception as e:
        latency_ms = int((time.time() - started) * 1000)
        return {
            "id": entry["id"],
            "state": "error",
            "error": str(e),
            "detail": "",
            "latency_ms": latency_ms,
        }

    latency_ms = int((time.time() - started) * 1000)
    if status_code >= 400:
        return {
            "id": entry["id"],
            "state": "error",
            "error": f"http {status_code}",
            "detail": body.decode("utf-8", errors="ignore")[:400],
            "latency_ms": latency_ms,
        }
    if "application/json" not in ctype:
        return {
            "id": entry["id"],
            "state": "error",
            "error": "invalid content-type",
            "detail": ctype or "n/a",
            "latency_ms": latency_ms,
        }

    try:
        obj = json.loads(body.decode("utf-8", errors="ignore"))
    except Exception:
        return {
            "id": entry["id"],
            "state": "error",
            "error": "invalid json",
            "detail": "",
            "latency_ms": latency_ms,
        }

    if obj.get("status") != "ok" or not obj.get("audio_b64"):
        return {
            "id": entry["id"],
            "state": "error",
            "error": "tts failed",
            "detail": str(obj)[:400],
            "latency_ms": latency_ms,
        }

    return {
        "id": entry["id"],
        "state": "ok",
        "detail": f"audio {len(obj.get('audio_b64', ''))} chars b64",
        "latency_ms": latency_ms,
    }


def _update_provider_status(result: dict[str, Any]) -> None:
    provider_id = result.get("id")
    if not provider_id:
        return
    _PROVIDER_STATUS[provider_id] = {
        "state": result.get("state", "unknown"),
        "detail": result.get("detail") or result.get("error") or "",
        "error": result.get("error"),
        "latency_ms": result.get("latency_ms"),
        "updated": time.time(),
    }


def providers_list_handler():
    if request.method == "OPTIONS":
        return _preflight()

    payload = []
    for entry_raw in _PROVIDER_DEFS:
        entry = _normalized_provider(entry_raw)
        service_alias = entry.get("service")
        payload.append(
            {
                "id": entry["id"],
                "label": entry["label"],
                "backend": entry["backend"],
                "voice": entry.get("voice"),
                "model": entry.get("model"),
                "description": entry.get("description", ""),
                "status": _provider_status_snapshot(entry["id"]),
                "service": service_alias,
                "service_state": _service_status(service_alias),
            }
        )

    return _cors(jsonify({"ok": True, "providers": payload}))


def providers_test_handler():
    if request.method == "OPTIONS":
        return _preflight()

    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception:
        payload = {}

    requested = payload.get("providers") or payload.get("provider")
    if requested is None:
        provider_ids = [entry["id"] for entry in _PROVIDER_DEFS]
    elif isinstance(requested, str):
        provider_ids = [requested]
    else:
        provider_ids = [str(x) for x in requested if x]

    results = []
    for provider_id in provider_ids:
        entry = _provider_lookup(provider_id)
        if entry is None:
            result = {"id": provider_id, "state": "error", "error": "unknown_provider", "detail": ""}
        else:
            result = _probe_provider(entry)
        results.append(result)
        _update_provider_status(result)

    return _cors(jsonify({"ok": True, "results": results}))


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

        # Przekaż ewentualne nadpisania (voice/model/format/backend)
        passthrough = {}
        for k in ("backend", "provider", "format", "voice", "model"):
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
        return _cors(
            jsonify(
                {
                    "ok": False,
                    "error": f"unexpected content-type from voice-web: {ctype}",
                }
            )
        ), 502

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
            return _cors(
                jsonify(
                    {
                        "ok": False,
                        "error": f"voice asr http error: {status}",
                        "body": snippet,
                    }
                )
            ), 502

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
        return _cors(
            jsonify(
                {
                    "ok": False,
                    "error": f"voice asr http error: {e.code}",
                    "body": err_body[:800],
                }
            )
        ), 502
    except Exception as e:
        return _cors(jsonify({"ok": False, "error": f"voice asr proxy failed: {e}"})), 502
