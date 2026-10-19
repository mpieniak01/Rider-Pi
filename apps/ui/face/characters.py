"""Static character shells, drawn once per skin/style change; no bitmap assets."""

SKINS = {
    "none": {"pl": "Bez oprawy", "en": "No character", "ink": None},
    "human": {"pl": "Piegusek", "en": "Freckles", "ink": (64, 39, 38)},
    "cat": {"pl": "Kotek", "en": "Kitten", "ink": (66, 39, 35)},
    "robot": {"pl": "Robocik", "en": "Little robot", "ink": (18, 47, 64)},
    "professional": {"pl": "Profesjonalna", "en": "Professional", "ink": (53, 53, 58)},
}


class _CharacterCanvas:
    def __init__(self, canvas):
        self.canvas = canvas
        self.size = min(canvas.im.size)

    def box(self, values):
        return tuple(round(value * self.size / 240) for value in values)

    def ellipse(self, values, color):
        self.canvas.ellipse(self.box(values), fill=color)

    def polygon(self, points, color):
        self.canvas.polygon([self.box(point) for point in points], fill=color)

    def line(self, points, color, width=3):
        self.canvas.line(
            [self.box(point) for point in points], fill=color, width=max(1, round(width * self.size / 240))
        )


def _draw_human(drawing):
    ellipse = drawing.ellipse
    polygon = drawing.polygon
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


def _draw_cat(drawing):
    ellipse = drawing.ellipse
    polygon = drawing.polygon
    line = drawing.line
    fur, inner = (221, 145, 83), (241, 180, 169)
    polygon([(18, 88), (18, 10), (79, 45)], fur)
    polygon([(222, 88), (222, 10), (161, 45)], fur)
    polygon([(28, 57), (29, 25), (57, 45)], inner)
    polygon([(212, 57), (211, 25), (183, 45)], inner)
    ellipse((22, 30, 218, 231), fur)
    polygon([(97, 33), (120, 46), (143, 33)], (174, 100, 58))
    for side in (-1, 1):
        for offset in (-8, 7):
            line([(120 + side * 72, 154 + offset), (120 + side * 107, 148 + offset)], SKINS["cat"]["ink"], 2)


def _draw_robot(drawing):
    canvas = drawing.canvas
    size = drawing.size
    box = drawing.box
    ellipse = drawing.ellipse
    line = drawing.line
    face, edge = (113, 190, 203), (62, 122, 144)
    line([(120, 24), (120, 10)], edge, 4)
    ellipse((114, 1, 126, 13), (242, 191, 91))
    for bounds in ((5, 91, 27, 144), (213, 91, 235, 144)):
        canvas.rounded_rectangle(box(bounds), radius=max(1, round(size * 0.025)), fill=edge)
    canvas.rounded_rectangle(box((22, 24, 218, 226)), radius=max(1, round(size * 0.15)), fill=face)
    for x in (40, 200):
        ellipse((x - 3, 47, x + 3, 53), edge)
    line([(81, 212), (159, 212)], edge, 3)


def _draw_professional(drawing):
    ellipse = drawing.ellipse
    polygon = drawing.polygon
    line = drawing.line
    face, hair = (203, 181, 165), (80, 76, 75)
    for bounds in ((19, 99, 42, 141), (198, 99, 221, 141)):
        ellipse(bounds, face)
    ellipse((29, 16, 211, 231), face)
    for bounds in ((25, 110, 35, 132), (205, 110, 215, 132)):
        ellipse(bounds, (171, 145, 135))
    # Rounded quadratic corners produce a softer oval/hair outline.
    points = [
        (34, 79),
        (36, 48),
        (56, 24),
        (99, 9),
        (154, 17),
        (193, 36),
        (206, 65),
        (202, 92),
        (191, 68),
        (179, 48),
        (149, 40),
        (118, 44),
        (92, 37),
        (69, 51),
        (46, 61),
        (42, 89),
    ]
    rounded = []
    for index, middle in enumerate(points):
        previous, following = points[index - 1], points[(index + 1) % len(points)]
        start = tuple((a + b) / 2 for a, b in zip(previous, middle))
        end = tuple((a + b) / 2 for a, b in zip(middle, following))
        for step in range(7):
            t = step / 6
            rounded.append(
                tuple((1 - t) ** 2 * a + 2 * (1 - t) * t * b + t * t * c for a, b, c in zip(start, middle, end))
            )
    polygon(rounded, hair)
    line([(48, 57), (69, 39), (89, 30)], (123, 116, 112), 2)
    line([(194, 64), (187, 46), (173, 36)], (123, 116, 112), 2)
    # Fixed nose geometry belongs in the cached shell, not the frame loop.
    line([(119, 121), (114, 147), (121, 151), (128, 147)], (155, 127, 115), 2)


def draw_character(canvas, skin):
    """Leave the shared animated feature area clear, including raised brows."""
    if skin == "none":
        return
    drawing = _CharacterCanvas(canvas)
    renderer = {"human": _draw_human, "cat": _draw_cat, "robot": _draw_robot, "professional": _draw_professional}.get(
        skin
    )
    if renderer is not None:
        renderer(drawing)
