import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from io import BytesIO
import pytest
from PIL import Image
from apps.ui.face.controller import FaceController

def get_pupil_bbox(img: Image.Image):
    arr = img.convert("L").point(lambda x: 0 if x < 32 else 255, mode='1')
    bbox = arr.getbbox()
    return bbox

def test_face_pupil_present():
    expr = "neutral"
    size = 240
    fc = FaceController(size=size, fps=1, idle=False)
    fc.set_expr(expr)
    img_bytes = fc.frame()
    img = Image.open(BytesIO(img_bytes)).convert("RGB")
    bbox = get_pupil_bbox(img)
    assert bbox is not None, "Brak źrenicy na wygenerowanym obrazie"
