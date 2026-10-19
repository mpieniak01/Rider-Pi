"""An understated adult face using the same seven animation channels."""

import math

from .friendly import _rounded


def draw_professional(canvas, state, style):
    size = min(canvas.im.size)
    ink = (53, 53, 58)
    eye = (239, 238, 230)
    iris = (86, 116, 125) if style != "minimal" else (85, 119, 110)
    dx, dy = state.eyes.gaze()
    blink = max(0.0, min(1.0, state.eyes.blink))
    stroke = max(2, round(size * 0.01))
    # Almond eyes and restrained gaze preserve legibility on the small LCD.
    for side in (-1, 1):
        ex, ey = size * (0.5 + side * 0.19), size * 0.445
        width = size * 0.225
        height = size * (0.12 if state.expr == "surprised" else 0.095) * max(0.04, 1 - blink)
        upper, lower = [], []
        for i in range(13):
            x = ex + width * (i / 12 - 0.5)
            arch = math.sin(i / 12 * math.pi)
            upper.append((x, ey - height * 0.55 * arch))
            lower.append((x, ey + height * 0.45 * arch))
        if blink > 0.93:
            canvas.line(
                [(x, ey + size * 0.008 * math.sin(i / 12 * math.pi)) for i, (x, _) in enumerate(upper)],
                fill=ink,
                width=stroke,
                joint="curve",
            )
        else:
            canvas.polygon(upper + list(reversed(lower)), fill=eye)
            radius = min(size * 0.031, height * 0.30)
            px, py = ex + dx * width * 0.18, ey + dy * height * 0.06
            canvas.ellipse((px - radius, py - radius, px + radius, py + radius), fill=iris)
            core = radius * 0.48
            canvas.ellipse((px - core, py - core, px + core, py + core), fill=(24, 31, 34))
            highlight = max(1, radius * 0.16)
            canvas.ellipse(
                (px - radius * 0.4, py - radius * 0.5, px - radius * 0.4 + highlight, py - radius * 0.5 + highlight),
                fill=eye,
            )
            canvas.line(upper, fill=ink, width=stroke, joint="curve")
            canvas.line(lower, fill=(128, 117, 111), width=max(1, stroke - 1), joint="curve")
        by = size * 0.325 - state.brows.lift_clamped() * size * 0.035
        tilt = state.brows.tilt_clamped() * side * size * 0.02
        brow = [
            (ex + (i / 12 - 0.5) * width, by - math.sin(i / 12 * math.pi) * size * 0.012 + (i / 6 - 1) * tilt)
            for i in range(13)
        ]
        canvas.line(brow, fill=ink, width=stroke + 1, joint="curve")

    _draw_mouth(canvas, state, size, stroke)


def _draw_mouth(canvas, state, size, stroke):
    cx, my, width = size * 0.5, size * 0.75, size * 0.30
    curve = state.mouth.curve
    if curve is None:
        curve = {"happy": 0.8, "sad": -0.65}.get(state.expr, 0.15)
    opened = state.mouth.open_clamped()
    if opened > 0.03:
        height = size * (0.012 + opened * 0.09)
        _rounded(
            canvas, (cx - width * 0.34, my - height / 2, cx + width * 0.34, my + height / 2), height / 3, (65, 42, 42)
        )
        if opened > 0.25:
            canvas.line(
                (cx - width * 0.2, my - height * 0.2, cx + width * 0.2, my - height * 0.2),
                fill=(222, 208, 194),
                width=max(1, stroke - 1),
            )
    else:
        points = [(cx + (i / 24 - 0.5) * width, my + curve * size * 0.065 * (1 - (i / 12 - 1) ** 2)) for i in range(25)]
        canvas.line(points, fill=(106, 63, 60), width=stroke + 1, joint="curve")
        for x, y in (points[0], points[-1]):
            canvas.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(106, 63, 60))
