"""Static character shells, drawn once per skin/style change; no bitmap assets."""

SKINS = {
    "none": {"pl": "Bez oprawy", "en": "No character", "ink": None},
    "human": {"pl": "Piegusek", "en": "Freckles", "ink": (64, 39, 38)},
    "cat": {"pl": "Kotek", "en": "Kitten", "ink": (66, 39, 35)},
    "robot": {"pl": "Robocik", "en": "Little robot", "ink": (18, 47, 64)},
}


def draw_character(canvas, skin):
    """Leave the shared animated feature area clear, including raised brows."""
    if skin == "none":
        return
    size = min(canvas.im.size)

    def box(values):
        return tuple(round(value * size / 240) for value in values)

    def ellipse(values, color):
        canvas.ellipse(box(values), fill=color)

    def polygon(points, color):
        canvas.polygon([box(point) for point in points], fill=color)

    def line(points, color, width=3):
        canvas.line([box(point) for point in points], fill=color, width=max(1, round(width * size / 240)))

    if skin == "human":
        face, hair = (238, 190, 148), (97, 58, 42)
        for bounds in ((7, 96, 42, 143), (198, 96, 233, 143)):
            ellipse(bounds, face)
        for bounds in ((15, 107, 34, 131), (206, 107, 225, 131)):
            ellipse(bounds, (211, 140, 112))
        ellipse((24, 16, 216, 232), face)
        polygon(
            [
                (30, 70),
                (32, 42),
                (47, 20),
                (86, 8),
                (158, 10),
                (189, 22),
                (209, 44),
                (210, 70),
                (193, 52),
                (175, 39),
                (149, 40),
                (130, 29),
                (108, 44),
                (85, 32),
                (58, 49),
                (46, 66),
            ],
            hair,
        )
        for x, y in ((52, 150), (63, 146), (74, 150), (166, 150), (177, 146), (188, 150)):
            ellipse((x - 1, y - 1, x + 1, y + 1), (167, 94, 68))
    elif skin == "cat":
        fur, inner = (221, 145, 83), (241, 180, 169)
        polygon([(18, 88), (18, 10), (79, 45)], fur)
        polygon([(222, 88), (222, 10), (161, 45)], fur)
        polygon([(28, 57), (29, 25), (57, 45)], inner)
        polygon([(212, 57), (211, 25), (183, 45)], inner)
        ellipse((22, 30, 218, 231), fur)
        polygon([(97, 33), (120, 46), (143, 33)], (174, 100, 58))
        for side in (-1, 1):
            for offset in (-8, 7):
                line([(120 + side * 72, 154 + offset), (120 + side * 107, 148 + offset)], SKINS[skin]["ink"], 2)
    elif skin == "robot":
        face, edge = (113, 190, 203), (62, 122, 144)
        line([(120, 24), (120, 10)], edge, 4)
        ellipse((114, 1, 126, 13), (242, 191, 91))
        for bounds in ((5, 91, 27, 144), (213, 91, 235, 144)):
            canvas.rounded_rectangle(box(bounds), radius=max(1, round(size * 0.025)), fill=edge)
        canvas.rounded_rectangle(box((22, 24, 218, 226)), radius=max(1, round(size * 0.15)), fill=face)
        for x in (40, 200):
            ellipse((x - 3, 47, x + 3, 53), edge)
        line([(81, 212), (159, 212)], edge, 3)
