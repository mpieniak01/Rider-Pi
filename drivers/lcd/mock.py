from __future__ import annotations

import json
from datetime import datetime

from PIL import Image

from common.secure_files import atomic_write


class MockFaceDriver:
    def __init__(self, cfg):
        self.cfg = cfg
        self.out_base = "/tmp/face_last"

    def push_png(self, img: Image.Image):
        atomic_write(f"{self.out_base}.png", lambda stream: img.save(stream, "PNG"))
        self._write_meta({"mode": "png", "size": img.size})

    def push_rgb565(self, buf: bytes, w: int, h: int):
        atomic_write(f"{self.out_base}.rgb565", lambda stream: stream.write(buf))
        # Dla testów: zapis PNG z bufora RGB565 (wizualizacja)
        try:
            import numpy as np

            arr = np.frombuffer(buf, dtype=">u2").reshape((h, w))
            r = ((arr >> 11) & 0x1F) << 3
            g = ((arr >> 5) & 0x3F) << 2
            b = (arr & 0x1F) << 3
            rgb = np.stack([r, g, b], axis=-1).astype("uint8")
            img = Image.fromarray(rgb, "RGB")
            atomic_write(f"{self.out_base}.png", lambda stream: img.save(stream, "PNG"))
        except Exception:
            # Nie blokuj testu jeśli numpy/PIL nie działa
            pass
        self._write_meta({"mode": "rgb565", "size": [w, h], "len": len(buf)})

    def _write_meta(self, extra):
        meta = {
            "ts": datetime.now().isoformat(),
            "panel": self.cfg.as_dict() if hasattr(self.cfg, "as_dict") else {},
        }
        meta.update(extra)
        data = json.dumps(meta, indent=2).encode("utf-8")
        atomic_write(f"{self.out_base}.meta.json", lambda stream: stream.write(data))
