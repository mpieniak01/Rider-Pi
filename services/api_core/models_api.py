"""Model inventory endpoints for Rider-Pi."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from flask import Response, jsonify, make_response, request

from .http_security import apply_cors

MODEL_EXTENSIONS: tuple[str, ...] = (".pt", ".onnx", ".tflite", ".gguf", ".bin")
CATEGORY_PATTERNS: dict[str, tuple[str, ...]] = {
    "vision": ("yolo", "detection", "vision", "mediapipe"),
    "voice_asr": ("whisper", "asr", "stt", "speech-to-text"),
    "voice_tts": ("piper", "tts", "text-to-speech", "voice"),
    "text": ("llama", "gpt", "mistral", "phi", "gemma", "qwen"),
}
MODELS_DIR = Path(os.getenv("RIDER_PI_MODELS_DIR", "data/models"))


def _corsify(resp: Response) -> Response:
    apply_cors(resp)
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def _detect_category(name: str) -> tuple[str, str]:
    lowered = name.lower()
    for category, patterns in CATEGORY_PATTERNS.items():
        if any(pat in lowered for pat in patterns):
            return category, patterns[0]
    return "unknown", "unknown"


def _scan_models() -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    if not MODELS_DIR.exists():
        return models

    for root, _, files in os.walk(MODELS_DIR):
        for filename in files:
            ext = Path(filename).suffix.lower()
            if ext not in MODEL_EXTENSIONS:
                continue
            file_path = Path(root) / filename
            try:
                size_mb = file_path.stat().st_size / (1024 * 1024)
            except OSError:
                size_mb = 0.0
            category, model_type = _detect_category(file_path.stem)
            try:
                relative_path = str(file_path.relative_to(MODELS_DIR))
            except ValueError:
                relative_path = str(file_path)
            models.append(
                {
                    "name": file_path.stem,
                    "path": relative_path,
                    "category": category,
                    "type": model_type,
                    "size_mb": round(size_mb, 2),
                    "format": ext.lstrip("."),
                }
            )
    return models


def installed_models_handler() -> tuple[Response, int]:
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204)), 204

    models = _scan_models()
    payload = {
        "models": models,
        "total": len(models),
        "root": str(MODELS_DIR),
    }
    return _corsify(jsonify(payload)), 200
