"""Describe existing local analysis engines without loading them or any weights."""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=8)
def _fingerprint(paths_and_stats):
    digests = []
    for name, _size, _mtime in paths_and_stats:
        digest = hashlib.sha256()
        with Path(name).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digests.append(digest.hexdigest())
    return digests[0] if len(digests) == 1 else hashlib.sha256("".join(digests).encode()).hexdigest()


def _artifact(paths):
    if not paths:
        return ""
    stats = []
    for path in paths:
        info = path.stat()
        stats.append((str(path.resolve()), info.st_size, info.st_mtime_ns))
    return _fingerprint(tuple(stats))


def catalog(pipeline):
    """Capabilities come from the same camera controller that owns local choice."""
    supported = pipeline.get("capabilities", {}).get("local_engines", [])
    profile = pipeline["profile"]
    ssd = Path(os.getenv("SSD_MODEL_DIR", "models/ssd"))
    paths = {
        "canny": [],
        "ssd": [ssd / "MobileNetSSD_deploy.prototxt", ssd / "MobileNetSSD_deploy.caffemodel"],
        "tflite": [Path(os.getenv("TFLITE_MODEL", "models/efficientdet_lite0.tflite"))],
    }
    labels = {"canny": "Canny (OpenCV)", "ssd": "MobileNet SSD", "tflite": "EfficientDet Lite0"}
    models = []
    active_profile = pipeline.get("active_profile")
    for engine, artifacts in paths.items():
        installed = engine in supported
        error = None if installed else "local_engine_unavailable"
        fingerprint = ""
        if installed:
            try:
                fingerprint = _artifact(artifacts)
            except OSError:
                installed, error = False, "local_model_artifact_unavailable"
        loaded = (
            installed
            and pipeline["state"] == "active"
            and isinstance(active_profile, dict)
            and active_profile.get("analysis_location") == "local"
            and active_profile.get("local_engine") == engine
        )
        models.append(
            {
                "id": "local-" + engine,
                "engine": engine,
                "label": labels[engine],
                "provider": "local",
                "task": "edges" if engine == "canny" else "object_detection",
                "installed": installed,
                "selectable": installed,
                "installation": "ready" if installed else "unavailable",
                "loaded": loaded,
                "sha256": fingerprint,
                "reason": error,
                "model_files": [path.name for path in artifacts],
                "drive_supported": False,
            }
        )
    return {
        "models": models,
        "provider": profile["analysis_location"],
        "pipeline_revision": pipeline["revision"],
        "selected_model_id": "local-" + profile["local_engine"],
        "active_model_id": next((row["id"] for row in models if row["loaded"]), None),
    }
