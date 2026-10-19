from __future__ import annotations

from types import SimpleNamespace

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


@pytest.mark.parametrize("enabled", [False, True])
def test_blink_can_trigger_look_when_coupling_enabled(monkeypatch, enabled):
    """Observe a complete blink with a fixed clock and horizontal look direction."""
    monkeypatch.setenv("FACE_IDLE_ENABLE", "1")
    monkeypatch.setenv("FACE_IDLE_LOOK_P", "0.0")
    monkeypatch.setenv("FACE_IDLE_LOOK_SEC", "0.0")
    monkeypatch.setenv("FACE_IDLE_BLINK_SEC", "0.5")
    monkeypatch.setenv("FACE_IDLE_JITTER", "0.0")
    monkeypatch.setenv("FACE_BLINK_SHIFT_PROB", str(float(enabled)))
    monkeypatch.setenv("FACE_PUPIL_DRIFT_AMP_K", "0.0")

    now = [0.0]
    # Angle0 points horizontally. The old test chose a random direction but only
    # measured X, and sampled wall-clock frames with a variable CPU/render delay.
    rng = SimpleNamespace(random=lambda: 0.0, uniform=lambda low, high: (low + high) / 2)
    fc = FaceController(size=240, fps=24, idle=True, clock=lambda: now[0], rng=rng)
    try:
        left_before, right_before = _pupil_centers(fc.frame_image())
        assert left_before is not None
        assert right_before is not None
        now[0] = 0.5
        fc.frame_image()  # Start the scheduled blink and optional coupled look.
        now[0] = 0.7  # Eyes are open again while the look remains active.
        left_after, right_after = _pupil_centers(fc.frame_image())
        assert left_after is not None
        assert right_after is not None
        distance = max(abs(left_after[0] - left_before[0]), abs(right_after[0] - right_before[0]))
        if enabled:
            assert distance >= 5.0
        else:
            assert distance < 0.5
    finally:
        fc.close()
