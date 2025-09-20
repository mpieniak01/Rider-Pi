import pathlib
import sys
from io import BytesIO

from PIL import Image

from apps.ui.face.controller import FaceController

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def get_pupil_bbox(img: Image.Image):
    # Prosty heurystyczny detektor czarnej źrenicy (największy ciemny obszar)
    arr = img.convert("L").point(lambda x: 0 if x < 32 else 255, mode="1")
    bbox = arr.getbbox()
    return bbox


def test_face_rotation_preserves_pupil():
    expr = "neutral"
    size = 240
    fc = FaceController(size=size, fps=1, idle=False)
    fc.set_expr(expr)
    img_bytes = fc.frame()
    img0 = Image.open(BytesIO(img_bytes)).convert("RGB")
    bbox0 = get_pupil_bbox(img0)
    assert bbox0 is not None, "Brak źrenicy na oryginalnym obrazie"
    for rot in [90, 180, 270]:
        img = img0.rotate(rot, expand=True)
        bbox = get_pupil_bbox(img)
        assert bbox is not None, f"Brak źrenicy po rotacji {rot}"
        # Sprawdź, że bbox nie jest drastycznie poza obrazem
        x0, y0, x1, y1 = bbox
        assert 0 <= x0 < x1 <= img.width
        assert 0 <= y0 < y1 <= img.height
