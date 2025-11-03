import time
from typing import Optional

import pytest
from PIL import Image

from apps.ui.face.controller import FaceController


def _pupil_centers(
    img: Image.Image,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    w, h = img.size
    px = img.load()
    cx, cy = w // 2, h // 2
    eye_dx = int(min(w, h) * 0.22)
    eye_w = int(min(w, h) * 0.28)
    eye_h = int(min(w, h) * 0.12)

    def scan_rect(x0, y0, x1, y1):
        xs, ys, n = 0, 0, 0
        for yy in range(max(y0, 0), min(y1, h)):
            for xx in range(max(x0, 0), min(x1, w)):
                r, g, b = px[xx, yy]
                if r < 10 and g < 10 and b < 10:
                    xs += xx
                    ys += yy
                    n += 1
        return None if n == 0 else (xs / n, ys / n)

    left = scan_rect(cx - eye_dx - eye_w // 2, cy - eye_h, cx - eye_dx + eye_w // 2, cy + eye_h)
    right = scan_rect(cx + eye_dx - eye_w // 2, cy - eye_h, cx + eye_dx + eye_w // 2, cy + eye_h)
    return left, right


@pytest.mark.timeout(6)
def test_look_gesture_shifts_pupils_right_or_left(monkeypatch):
    """
    Sprawdzamy, że gest „look” powoduje wyraźny przesuw źrenic w osi X.
    Test jest odporny na easing: zbiera kilka klatek i szuka maks. odchylenia
    względem pozycji bazowej dla obu kierunków.
    """
    # Stabilne środowisko: wyłącz idle i dryf źrenic
    monkeypatch.setenv("FACE_IDLE_ENABLE", "0")
    monkeypatch.setenv("FACE_PUPIL_DRIFT_AMP_K", "0.0")

    fc = FaceController(size=240, fps=20, idle=False)

    # Pozycja startowa
    img0 = fc.frame_image()
    l0, r0 = _pupil_centers(img0)
    assert l0 and r0
    base_lx, base_rx = l0[0], r0[0]

    def run_look(amp: float) -> tuple[float, float]:
        """Zwraca (max_dx_left, max_dx_right) względem pozycji bazowej."""
        fc.do("look", t=0.25, amp=amp)
        max_dx_l, max_dx_r = 0.0, 0.0
        xs_l, xs_r = [], []
        # ok. 12 klatek ~ 0.6 s przy 20 fps
        for _ in range(12):
            img = fc.frame_image()
            l1, r1 = _pupil_centers(img)
            if l1 and r1:
                dx_l = l1[0] - base_lx
                dx_r = r1[0] - base_rx
                max_dx_l = max(max_dx_l, abs(dx_l))
                max_dx_r = max(max_dx_r, abs(dx_r))
                xs_l.append(dx_l)
                xs_r.append(dx_r)
            time.sleep(0.05)
        return max_dx_l, max_dx_r

    # Próba w prawo i w lewo — bierzemy tę, która wyraźniej zadziała
    THRESH = 3.0  # px

    right_l, right_r = run_look(+0.6)
    left_l, left_r = run_look(-0.6)

    max_right = max(right_l, right_r)
    max_left = max(left_l, left_r)

    assert (max_right >= THRESH) or (max_left >= THRESH), (
        "Gest 'look' powinien wyraźnie przesunąć źrenice w prawo lub w lewo "
        f"(≥{THRESH}px). Observed: right={max_right:.1f}px, left={max_left:.1f}px"
    )
