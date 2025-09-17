import os
import json
from PIL import Image
from typing import Any

class MockDriver:
    def __init__(self):
        self.last_image_path = '/tmp/face_last.png'
        self.last_rgb565_path = '/tmp/face_last.rgb565'
        self.last_meta_path = '/tmp/face_last.meta.json'

    def push_png(self, img: Image) -> None:
        img.save(self.last_image_path)

    def push_rgb565(self, rgb565_data: bytes, width: int, height: int) -> None:
        with open(self.last_rgb565_path, 'wb') as f:
            f.write(rgb565_data)
        self._save_metadata(width, height)

    def _save_metadata(self, width: int, height: int) -> None:
        metadata = {
            'width': width,
            'height': height,
            'format': 'RGB565'
        }
        with open(self.last_meta_path, 'w') as f:
            json.dump(metadata, f)

def make_driver(kind: str, cfg: Any) -> MockDriver:
    if kind == "mock":
        return MockDriver()
    raise ValueError(f"Unknown driver kind: {kind}")