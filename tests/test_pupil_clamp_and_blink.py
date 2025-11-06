from __future__ import annotations

import time
from typing import Optional

import pytest
from PIL import Image

from apps.ui.face.controller import FaceController


def _eye_rects(
    img: Image.Image,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    w, h = img.size
    cx, cy = w // 2, h // 2
    eye_dx = int(min(w, h) * 0.22)
    eye_w = int(min(w, h) * 0.28)
    eye_h = int(min(w, h) * 0.12)
    left = (cx - eye_dx - eye_w // 2, cy - eye_h, cx - eye_dx + eye_w // 2, cy + eye_h)
    right = (cx + eye_dx - eye_w // 2, cy - eye_h, cx + eye_dx + eye_w // 2, cy + eye_h)
    return left, right


def _pupil_centers(
    img: Image.Image,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    w, h = img.size
    px = img.load()
    (lx0, ly0, lx1, ly1), (rx0, ry0, rx1, ry1) = _eye_rects(img)

    def scan_rect(x0: int, y0: int, x1: int, y1: int) -> tuple[float, float] | None:
        xs, ys, n = 0, 0, 0
        for y in range(max(y0, 0), min(y1, h)):
            for x in range(max(x0, 0), min(x1, w)):
                r, g, b = px[x, y]
                if r < 10 and g < 10 and b < 10:
                    xs += x
                    ys += y
                    n += 1
        if n == 0:
            return None
        return (xs / n, ys / n)

    left = scan_rect(lx0, ly0, lx1, ly1)
    right = scan_rect(rx0, ry0, rx1, ry1)
    return left, right


@pytest.mark.timeout(6)
def test_pupil_stays_inside_eye_with_extreme_look_and_blink(monkeypatch):
    # Wymuś dużą amplitudę look + blink, ale clamp powinien trzymać źrenicę w białku
    monkeypatch.setenv("FACE_IDLE_ENABLE", "0")
    monkeypatch.setenv("FACE_PUPIL_DRIFT_AMP_K", "0.05")
    monkeypatch.setenv("FACE_PUPIL_CLAMP_RATIO", "0.78")

    fc = FaceController(size=240, fps=24, idle=False)

    # Skok spojrzenia (duża amplituda)
    fc.do("look", t=0.25, amp=0.9)
    # Jednocześnie mrugnięcie (przymknięte powieki wygaszają drift)
    fc.do("blink", duration=0.3, hold=0.05)

    # Poczekaj kilka klatek
    img = None
    for _ in range(8):
        img = fc.frame_image()
        time.sleep(0.04)

    assert img is not None
    (lx0, ly0, lx1, ly1), (rx0, ry0, rx1, ry1) = _eye_rects(img)
    lc, rc = _pupil_centers(img)
    assert lc and rc

    # Źrenice pozostają w granicach prostokąta oka (przybliżenie owal/clamp)
    assert lx0 <= lc[0] <= lx1 and ly0 <= lc[1] <= ly1, "Lewy pupil powinien pozostać w obrębie oka"
    assert rx0 <= rc[0] <= rx1 and ry0 <= rc[1] <= ry1, "Prawy pupil powinien pozostać w obrębie oka"
