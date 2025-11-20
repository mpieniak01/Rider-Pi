from __future__ import annotations

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


@pytest.mark.timeout(8)
def test_blink_can_trigger_look_when_coupling_enabled(monkeypatch):
    """
    Sprzęgło: przy BLINK_SHIFT_PROB=1.0 i wyłączonym idle-look, w oknie kilku
    mrugnięć powinien zajść „skok” spojrzenia widoczny w renderze (drift=0).
    """
    # Włącz idle, ale wyłącz spontaniczny look – sprzęgło ma go uruchomić
    monkeypatch.setenv("FACE_IDLE_ENABLE", "1")
    monkeypatch.setenv("FACE_IDLE_LOOK_P", "0.0")
    monkeypatch.setenv("FACE_IDLE_LOOK_SEC", "0.0")
    # Blink często, by mieć kilka prób w krótkim oknie
    monkeypatch.setenv("FACE_IDLE_BLINK_SEC", "0.5")
    # Sprzęgło: 100% szansy na look przy mrugnięciu
    monkeypatch.setenv("FACE_BLINK_SHIFT_PROB", "1.0")
    # Bez driftu, żeby nie mylił pomiaru
    monkeypatch.setenv("FACE_PUPIL_DRIFT_AMP_K", "0.0")

    fc = FaceController(size=240, fps=24, idle=True)

    img0 = fc.frame_image()
    l0, r0 = _pupil_centers(img0)
    assert l0 and r0

    # Obserwuj przez kilka mrugnięć
    thresh = 5.0  # istotna zmiana px
    t_end = time.time() + 3.5
    seen_jump = False

    prev = (l0, r0)
    while time.time() < t_end:
        img = fc.frame_image()
        l1, r1 = _pupil_centers(img)
        if not (l1 and r1 and prev[0] and prev[1]):
            prev = (l1, r1)
            continue
        # Szukamy nagle większej zmiany w osi X (miękki skok „look”)
        dx_l = abs(l1[0] - prev[0][0])
        dx_r = abs(r1[0] - prev[1][0])
        if max(dx_l, dx_r) >= thresh:
            seen_jump = True
            break
        prev = (l1, r1)
        time.sleep(0.04)

    assert seen_jump, (
        "Przy sprzęgle=1.0 i braku idle-look powinien wystąpić „skok” spojrzenia (≥5 px) po którymś mrugnięciu."
    )
