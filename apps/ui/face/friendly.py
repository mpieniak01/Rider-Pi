"""Small procedural faces: no assets, file reads, hardware or per-frame scaling."""

import math

PALETTES = {
    "friendly": {"background": (20, 39, 57), "eye": (242, 249, 255), "iris": (75, 188, 226), "accent": (238, 141, 130)},
    "minimal": {"background": (22, 34, 48), "eye": (169, 235, 222), "iris": (39, 120, 141), "accent": (97, 186, 183)},
}


def _rounded(canvas, box, radius, fill):
    # Integer bounds also work with the older Pillow installed on CM4.
    box = tuple(round(value) for value in box)
    radius = min(int(radius), (box[2] - box[0]) // 2, (box[3] - box[1]) // 2)
    canvas.rounded_rectangle(box, radius=max(0, radius), fill=fill)


def draw_friendly(canvas, state, style):
    palette = PALETTES[style]
    size = min(canvas.im.size)
    cx, cy = size / 2, size * 0.46
    eyes, brows, mouth = state.eyes, state.brows, state.mouth
    blink = max(0.0, min(1.0, eyes.blink))
    dx, dy = eyes.gaze()
    curve = mouth.curve
    if curve is None:
        shape = state.expr if mouth.shape == "auto" else mouth.shape
        curve = {"happy": 0.75, "sad": -0.65}.get(shape, 0.15)
    open_level = mouth.open_clamped()
    eye_w = size * (0.29 if style == "friendly" else 0.27)
    eye_h = size * (0.32 if style == "friendly" else 0.25)
    eye_h *= max(0.04, 1 - blink)
    stroke = max(2, round(size * 0.018))
    for side in (-1, 1):
        ex = cx + side * size * 0.215 + dx * size * 0.016
        ey = cy + dy * size * 0.014
        box = (ex - eye_w / 2, ey - eye_h / 2, ex + eye_w / 2, ey + eye_h / 2)
        if blink > 0.93:
            canvas.line((box[0], ey, box[2], ey), fill=palette["eye"], width=stroke)
        else:
            _rounded(canvas, box, min(eye_w, eye_h) * 0.47, palette["eye"])
            radius = min(size * 0.065, eye_h * 0.38)
            px = ex + dx * (eye_w / 2 - radius - size * 0.014)
            py = ey + dy * (eye_h / 2 - radius - size * 0.006)
            canvas.ellipse((px - radius, py - radius, px + radius, py + radius), fill=palette["iris"])
            core = radius * 0.62
            canvas.ellipse((px - core, py - core, px + core, py + core), fill=(0, 0, 0))
            highlight = radius * 0.22
            canvas.ellipse(
                (
                    px - radius * 0.5,
                    py - radius * 0.6,
                    px - radius * 0.5 + highlight * 2,
                    py - radius * 0.6 + highlight * 2,
                ),
                fill=palette["eye"],
            )
        by = cy - size * 0.23 - brows.lift_clamped() * size * 0.045
        tilt = brows.tilt_clamped() * side * size * 0.025
        points = [
            (ex + (i / 12 - 0.5) * size * 0.20, by - math.sin(i / 12 * math.pi) * size * 0.025 + (i / 6 - 1) * tilt)
            for i in range(13)
        ]
        canvas.line(points, fill=palette["eye"], width=stroke, joint="curve")
        if style == "friendly":
            cheek_y = cy + size * 0.215
            canvas.ellipse(
                (ex - size * 0.039, cheek_y - size * 0.016, ex + size * 0.039, cheek_y + size * 0.016),
                fill=palette["accent"],
            )
    my, mw = size * 0.73, size * 0.29
    if open_level > 0.03:
        height = size * (0.02 + open_level * 0.12)
        _rounded(
            canvas,
            (cx - mw * 0.34, my - height / 2, cx + mw * 0.34, my + height / 2),
            min(mw * 0.20, height / 2),
            palette["eye"],
        )
        canvas.ellipse((cx - mw * 0.19, my, cx + mw * 0.19, my + height * 0.35), fill=palette["accent"])
    else:
        points = [(cx + (i / 24 - 0.5) * mw, my + curve * size * 0.075 * (1 - (i / 12 - 1) ** 2)) for i in range(25)]
        canvas.line(points, fill=palette["eye"], width=stroke + 1, joint="curve")
        for x, y in (points[0], points[-1]):
            canvas.ellipse((x - stroke / 2, y - stroke / 2, x + stroke / 2, y + stroke / 2), fill=palette["eye"])
