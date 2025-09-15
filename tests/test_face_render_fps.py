import time
from apps.ui.face.renderer import FaceRenderer

def test_smoke_fps():
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
    N = 20
    t0 = time.time()
    for _ in range(N):
        renderer.render_png_bytes(DummyFaceState())
    dt = time.time() - t0
    fps = N / dt
    print(f"[smoke] FPS: {fps:.2f}")
    assert fps > 10, f"FPS too low: {fps:.2f}"
