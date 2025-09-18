"""HTTP API for the voice assistant."""
from __future__ import annotations

import argparse
import io
import time
import wave
from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from flask import Flask, Response, jsonify, request

from . import config as voice_config
from . import logging as voice_logging
from .asr import ASRConfig, transcribe
from .service import VoiceService
from .tts import TTSConfig, synthesize


def _merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            dst[key] = _merge(dict(dst[key]), value)
        else:
            dst[key] = value
    return dst


def create_app(config_path: str | None = None) -> Flask:
    base_config = voice_config.load(config_path)
    voice_logging.configure(base_config.get("logging", {}).get("level"))
    app = Flask(__name__)
    app.config["VOICE_BASE_CONFIG"] = base_config
    app.config["VOICE_START_TS"] = time.time()

    @app.get("/healthz")
    def healthz() -> Response:
        cfg = app.config["VOICE_BASE_CONFIG"]
        payload = {
            "ok": True,
            "uptime_s": round(time.time() - app.config["VOICE_START_TS"], 3),
            "backends": {
                "asr": cfg["asr"]["backend"],
                "tts": cfg["tts"]["backend"],
                "capture": cfg["capture"]["backend"],
            },
        }
        return jsonify(payload)

    @app.post("/tts")
    def tts_route() -> Response:
        data = request.get_json(silent=True) or {}
        text = data.get("text")
        if not text:
            return jsonify({"ok": False, "error": "text required"}), 400
        overrides = {"tts": {k: v for k, v in data.items() if k in {"backend", "voice", "model", "format", "piper_model", "piper_config"}}}
        config = _merge(deepcopy(app.config["VOICE_BASE_CONFIG"]), overrides)
        audio, sample_rate, fmt = synthesize(text, TTSConfig(**config["tts"]))
        mimetype = "audio/wav" if fmt == "wav" else "audio/mpeg"
        headers = {"X-Sample-Rate": str(sample_rate)} if sample_rate else {}
        return Response(audio, mimetype=mimetype, headers=headers)

    @app.post("/asr")
    def asr_route() -> Response:
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "file field required"}), 400
        file = request.files["file"]
        buf = io.BytesIO(file.read())
        try:
            with wave.open(buf) as wf:  # type: ignore[name-defined]
                sample_rate = wf.getframerate()
                frames = wf.readframes(wf.getnframes())
        except Exception:
            return jsonify({"ok": False, "error": "invalid audio"}), 400
        overrides = {"asr": {}}
        backend = request.form.get("backend")
        if backend:
            overrides["asr"]["backend"] = backend
        lang = request.form.get("lang")
        if lang:
            overrides["asr"]["language"] = lang
        config = _merge(deepcopy(app.config["VOICE_BASE_CONFIG"]), overrides)
        transcript = transcribe(frames, sample_rate, ASRConfig(**config["asr"]))
        return jsonify({"ok": True, "text": transcript.text, "language": transcript.language})

    @app.post("/capture")
    def capture_route() -> Response:
        payload = request.get_json(silent=True) or {}
        config = _merge(deepcopy(app.config["VOICE_BASE_CONFIG"]), payload)
        service = VoiceService(config)
        result = service.once(speak=False)
        if not result or not result.audio:
            return jsonify({"ok": False, "error": "capture failed"}), 500
        mimetype = "audio/wav" if result.audio_format == "wav" else "audio/mpeg"
        headers = {
            "X-Transcript": result.transcript.text,
            "X-Intent": result.intent.kind,
            "X-Latency": str(round(result.latency_s, 3)),
        }
        return Response(result.audio, mimetype=mimetype, headers=headers)

    return app


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Voice HTTP API")
    parser.add_argument("--config", default=None)
    parser.add_argument("--bind", default="127.0.0.1:8092")
    args = parser.parse_args(list(argv) if argv is not None else None)
    app = create_app(args.config)
    host, port = args.bind.split(":")
    app.run(host=host, port=int(port), debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
