from __future__ import annotations

from typing import Literal

import numpy as np
from PIL import Image


def to_rgb565(img: Image.Image) -> bytes:
    arr = np.array(img.convert("RGB"), dtype=np.uint8)
    r = (arr[..., 0] >> 3).astype(np.uint16)
    g = (arr[..., 1] >> 2).astype(np.uint16)
    b = (arr[..., 2] >> 3).astype(np.uint16)
    rgb565 = (r << 11) | (g << 5) | b
    return rgb565.astype(">u2").tobytes()


def apply_rotate(img: Image.Image, deg: int) -> Image.Image:
    if deg == 0:
        return img
    return img.rotate(-deg, expand=True)


def fit_strategy(
    img: Image.Image, mode: Literal["fill", "fit", "stretch"], size=(240, 240)
) -> Image.Image:
    if mode == "stretch":
        return img.resize(size)
    elif mode == "fit":
        img = img.copy()
        img.thumbnail(size)
        bg = Image.new("RGB", size, (0, 0, 0))
        bg.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
        return bg
    else:  # fill
        ratio = max(size[0] / img.width, size[1] / img.height)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size)
        left = (img.width - size[0]) // 2
        top = (img.height - size[1]) // 2
        return img.crop((left, top, left + size[0], top + size[1]))
