from __future__ import annotations
from typing import Iterable, Optional
import time, random

from .renderer import FaceRenderer
from .animator import Animator
from .gestures import GESTURES

class FaceController:
    """Przyjmuje komendy (gesty/polityki), woła animator i renderer."""
    def __init__(self, size: int = 240, fps: int = 12, idle: bool = True):
        self.size, self.fps = size, fps
        self.anim = Animator()
        # Domyślna konfiguracja geometryczna (zgodna z nowym rendererem)
        cfg = type("Cfg", (), {"mouth_y_k": 0.215, "brow_y_k": 0.21, "brow_h_k": 0.09, "head_ky": 1.04})()
        self.renderer = FaceRenderer(cfg, size=size)
        self._idle_enabled = idle
        self._speak_level = 0.0   # 0..1

    # --- API ---
    def set_expr(self, expr: str) -> None:
        self.anim.state.expr = expr

    def do(self, name: str, prio: int = 10, mode: str = "blend", **kwargs) -> None:
        spec = GESTURES[name](**kwargs)
        self.anim.start(spec, prio=prio, mode=mode)

    def stop(self, channel: Optional[str] = None) -> None:
        self.anim.stop(channel)

    def set_idle(self, on: bool) -> None:
        self._idle_enabled = on

    def speaking(self, level: float) -> None:
        """Ustaw poziom mowy (0..1) → mapuje na mouth.open."""
        self._speak_level = max(0.0, min(1.0, float(level)))

    # --- Polityki (lekko) ---
    def _policy_idle_tick(self) -> None:
        if not self._idle_enabled:
            return
        # micro-look
        if random.random() < 0.02:
            self.do("look", dx=random.uniform(-0.35, 0.35), dy=random.uniform(-0.18, 0.18), t=0.18)
        # sporadyczny blink
        if random.random() < 0.012:
            self.do("blink", duration=0.12)

    def _policy_speaking_apply(self) -> None:
        # prosta mapa głośności na otwarcie ust
        self.anim.state.mouth.open = self._speak_level

    # --- Klatki ---
    def frame(self) -> bytes:
        st = self.anim.tick()
        self._policy_speaking_apply()
        self._policy_idle_tick()
        return self.renderer.render_png_bytes(st)

    def loop(self, secs: float) -> Iterable[bytes]:
        dt = 1.0 / max(1, self.fps)
        t0 = time.time()
        while time.time() - t0 < secs:
            yield self.frame()
            time.sleep(dt)
