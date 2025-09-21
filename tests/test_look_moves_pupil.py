import time
from typing import Optional

import pytest
from PIL import Image

from apps.ui.face.controller import FaceController


def _pupil_centers(
    img: Image.Image,
) -> tuple[Optional[tuple[float, float]], Optional[tuple[float, float]]]:
    w, h = img.size
    px = img.load()
    cx, cy = w // 2, h // 2
    eye_dx = int(min(w, h) * 0.22)
    eye_w = int(min(w, h) * 0.28)
    eye_h = int(min(w, h) * 0.12)

    def scan_rect(x0: int, y0: int, x1: int, y1: int) -> Optional[tuple[float, float]]:
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

    left = scan_rect(
        cx - eye_dx - eye_w // 2,
        cy - eye_h,
        cx - eye_dx + eye_w // 2,
        cy + eye_h,
    )
    right = scan_rect(
        cx + eye_dx - eye_w // 2,
        cy - eye_h,
        cx + eye_dx + eye_w // 2,
        cy + eye_h,
    )
    return left, right


@pytest.mark.timeout(6)
def test_look_gesture_shifts_pupils_right_or_left(monkeypatch):
    # Stabilne środowisko: wyłącz idle, zostaw drift minimalny
    monkeypatch.setenv("FACE_IDLE_ENABLE", "0")
    monkeypatch.setenv("FACE_PUPIL_DRIFT_AMP_K", "0.0")

    fc = FaceController(size=240, fps=20, idle=False)

    # Klatka startowa
    img0 = fc.frame_image()
    l0, r0 = _pupil_centers(img0)
    assert l0 and r0

    # W prawo
    fc.do("look", t=0.25, amp=0.6)
    for _ in range(6):
        _ = fc.frame_image()
        time.sleep(0.05)
    l1, r1 = _pupil_centers(fc.frame_image())
    assert l1 and r1
    moved_right = (l1[0] > l0[0]) and (r1[0] > r0[0])

    # W lewo
    fc.do("look", t=0.25, amp=-0.6)
    for _ in range(6):
        _ = fc.frame_image()
        time.sleep(0.05)
    l2, r2 = _pupil_centers(fc.frame_image())
    assert l2 and r2
    moved_left = (l2[0] < l1[0]) and (r2[0] < r1[0])

    # Co najmniej jeden kierunek powinien zadziałać
    assert moved_right or moved_left, (
        "Gest 'look' powinien wyraźnie przesunąć źrenice w prawo lub w lewo."
    )
