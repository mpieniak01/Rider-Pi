import os
import time

import pytest
from PIL import Image

from apps.ui.face.controller import FaceController


# --- proste wykrywanie środka źrenic przez skan pikseli czarnych -------------
def _pupil_centers(img: Image.Image):
    w, h = img.size
    px = img.load()

    # Szacowanie rejonów oczu (symetrycznie wokół środka)
    cx, cy = w // 2, h // 2
    eye_dx = int(min(w, h) * 0.22)
    eye_w = int(min(w, h) * 0.28)
    eye_h = int(min(w, h) * 0.12)

    def scan_rect(x0, y0, x1, y1):
        xs, ys, n = 0, 0, 0
        for y in range(max(y0, 0), min(y1, h)):
            for x in range(max(x0, 0), min(x1, w)):
                r, g, b = px[x, y]
                if r < 10 and g < 10 and b < 10:  # źrenica ~ czarna
                    xs += x
                    ys += y
                    n += 1
        if n == 0:
            return None
        return (xs / n, ys / n)

    left = scan_rect(cx - eye_dx - eye_w // 2, cy - eye_h, cx - eye_dx + eye_w // 2, cy + eye_h)
    right = scan_rect(cx + eye_dx - eye_w // 2, cy - eye_h, cx + eye_dx + eye_w // 2, cy + eye_h)
    return left, right


@pytest.mark.timeout(5)
def test_pupil_drift_changes_bbox(tmp_path, monkeypatch):
    # Wzmacniamy drift i częstotliwość, by ruch był pewny
    monkeypatch.setenv("FACE_PUPIL_DRIFT_AMP_K", "0.08")
    monkeypatch.setenv("FACE_PUPIL_DRIFT_FREQ", "2.5")
    monkeypatch.setenv("FACE_IDLE_ENABLE", "0")  # bez idle gestów, tylko drift

    fc = FaceController(size=240, fps=12, idle=False)

    img1 = fc.frame_image()
    time.sleep(0.15)  # odczekaj chwilę, by sin/cos zmienił fazę
    img2 = fc.frame_image()

    l1, r1 = _pupil_centers(img1)
    l2, r2 = _pupil_centers(img2)

    # oczekujemy jakiejś zmiany pozycji (drift)
    assert l1 and l2 and r1 and r2, "Źrenice muszą być wykrywalne"
    l_dx = abs(l2[0] - l1[0]) + abs(l2[1] - l1[1])
    r_dx = abs(r2[0] - r1[0]) + abs(r2[1] - r1[1])
    assert l_dx > 0.5 or r_dx > 0.5, f"Drift powinien poruszyć źrenice (l={l_dx:.2f}, r={r_dx:.2f})"
