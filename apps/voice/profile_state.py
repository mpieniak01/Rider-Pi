"""Small voice worker heartbeat, written by its existing process only."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path


def write_status(status: dict) -> None:
    root = Path(os.getenv("FEATURE_STATE_PATH", "/run/rider-motion/feature_state.json")).parent
    root.mkdir(parents=True, exist_ok=True)
    path = root / "rider-voice-web.service.json"
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".voice-profile-", dir=str(root))
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(
                {"unit": "rider-voice-web.service", "pid": os.getpid(), "observed_at": time.time(), **status},
                stream,
                allow_nan=False,
            )
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
