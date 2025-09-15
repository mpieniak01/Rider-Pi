import io
from PIL import Image
from apps.ui.face.controller import FaceController

def png_to_img(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")

def count_color(img, rgb):
    return sum(1 for px in img.getdata() if px == rgb)

def test_pupil_exists_during_blink():
    fc = FaceController(size=240, fps=24, idle=False)
    fc.set_expr("neutral")
    fc.do("blink", duration=0.20)
    frames = [png_to_img(p) for p in fc.loop(0.25)]
    # w żadnej klatce liczba czarnych pikseli nie może spaść do zera
    for im in frames:
        blacks = count_color(im, (0,0,0))
        assert blacks > 300, f"pupil lost (black count={blacks})"
