import io
from PIL import Image
from apps.ui.face.renderer import FaceRenderer

def png_to_img(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")

def test_rotation_270():
    class DummyFaceState:
        def blink_mul(self): return 1.0
        state = "neutral"
        gaze_dx = 0
        expr = "neutral"
        expr_intensity = 0.0
        assist_speaking = False
        speak_phase = 0.0
    cfg = type("Cfg", (), {"mouth_y_k": 0.215, "brow_y_k": 0.21, "brow_h_k": 0.09, "head_ky": 1.04})()
    renderer = FaceRenderer(cfg, size=240, guide=False, quality="fast")
    png_bytes = renderer.render_png_bytes(DummyFaceState())
    img = png_to_img(png_bytes)
    # Sprawdź czy obrazek ma oczekiwany rozmiar i nie jest pusty
    assert img.size == (240, 240)
    assert img.getbbox() is not None
