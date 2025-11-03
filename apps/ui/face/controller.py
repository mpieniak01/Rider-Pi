from __future__ import annotations

import os
import random
import time
from collections import deque
from collections.abc import Iterable
from io import BytesIO

from PIL import Image

from .animator import Animator
from .gestures import GESTURES
from .renderer import FaceRenderer


def _clamp01(x: float) -> float:
    try:
        x = float(x)
    except Exception:
        return 0.0
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


class FaceController:
    """Przyjmuje komendy (gesty/polityki), woła animator i renderer."""

    def __init__(self, size: int = 240, fps: int = 12, idle: bool = True):
        self.size, self.fps = size, fps

        env_idle = os.getenv("FACE_IDLE_ENABLE")
        self.idle = (str(env_idle).lower() not in {"0", "false", "no"}) if env_idle is not None else idle

        self.renderer = FaceRenderer(cfg={}, size=size, guide=False, quality="fast")
        self.anim = Animator()
        self._speaking = False

        # IDLE
        self._idle_blink_every = float(os.getenv("FACE_IDLE_BLINK_SEC", "3.0"))
        self._idle_soft_blink_every = float(os.getenv("FACE_IDLE_SOFT_BLINK_SEC", "0.0"))
        self._idle_look_p = float(os.getenv("FACE_IDLE_LOOK_P", "0.0"))
        self._idle_look_every = float(os.getenv("FACE_IDLE_LOOK_SEC", "0.0"))
        self._idle_jitter = float(os.getenv("FACE_IDLE_JITTER", "0.15"))
        self._blink_shift_prob = float(os.getenv("FACE_BLINK_SHIFT_PROB", "0.12"))

        # Gesty
        self._blink_dur = float(os.getenv("FACE_GESTURE_BLINK_DUR", "0.16"))
        self._blink_hold = float(os.getenv("FACE_GESTURE_BLINK_HOLD", "0.02"))
        self._look_t = float(os.getenv("FACE_GESTURE_LOOK_T", "0.55"))
        self._look_amp = float(os.getenv("FACE_GESTURE_LOOK_AMP", "0.42"))

        # Usta override
        raw_shape = os.getenv("FACE_MOUTH_SHAPE", "").strip().lower()
        self._mouth_shape_override = raw_shape if raw_shape in {"happy", "neutral", "sad"} else ""
        self._mouth_open_override = os.getenv("FACE_MOUTH_OPEN", "").strip()

        # Debug
        self._debug_mouth = os.getenv("FACE_DEBUG_MOUTH", "0").lower() not in {
            "0",
            "false",
            "no",
        }
        self._last_dbg = 0.0

        # Timery
        now = time.time()
        self._next_blink_ts = (
            now + self._jittered(self._idle_blink_every) if self._idle_blink_every > 0 else float("inf")
        )
        self._next_soft_blink_ts = (
            now + self._jittered(self._idle_soft_blink_every) if self._idle_soft_blink_every > 0 else float("inf")
        )
        self._next_look_ts = now + self._jittered(self._idle_look_every) if self._idle_look_every > 0 else float("inf")

        self._blink_cooldown_until = 0.0
        self._soft_blink_block_until = 0.0

        # Mood transitions
        self._trans_step_s = float(os.getenv("FACE_TRANS_STEP_S", "0.35"))
        self._trans_dwell_s_default = float(os.getenv("FACE_TRANS_DWELL_S", "0.18"))

        self._mood_current = "neutral"
        self._mood_queue: deque[tuple[str, float, str]] = deque()
        self._mood_last_softblink_at = 0.0

        init_shape = self._mouth_shape_override or ""
        if init_shape in {"happy", "neutral", "sad"}:
            self.anim.state.mouth.shape = init_shape
            self._mood_current = init_shape
        else:
            expr = getattr(self.anim.state, "expr", "neutral")
            start = {"happy": "happy", "sad": "sad"}.get(expr, "neutral")
            self.anim.state.mouth.shape = start
            self._mood_current = start

    def _jittered(self, base: float) -> float:
        if base <= 0:
            return float("inf")
        j = max(0.0, self._idle_jitter)
        factor = 1.0 + (random.uniform(-j, j))
        return max(0.6 * base, base * factor)

    def _schedule_next(self, kind: str, base: float) -> None:
        t = time.time() + self._jittered(base)
        if kind == "blink":
            self._next_blink_ts = t
        elif kind == "soft":
            self._next_soft_blink_ts = t
        elif kind == "look":
            self._next_look_ts = t

    # API
    def set_expr(self, expr: str) -> None:
        self.anim.state.expr = str(expr or "neutral")

    def speak(self, on: bool = True) -> None:
        self._speaking = bool(on)

    def do(self, name: str, **kwargs) -> None:
        spec_fn = GESTURES.get(name)
        if not spec_fn:
            return
        spec = spec_fn(**kwargs)
        self.anim.start(spec, prio=10, mode="blend")

    # Mood transitions
    def set_mood(self, target: str, via_neutral: bool = True, dwell_s: float | None = None) -> None:
        target = (target or "neutral").lower()
        if target not in {"happy", "neutral", "sad"}:
            return

        now = time.time()
        cur = self._mood_current or "neutral"
        self._mood_queue.clear()

        dwell = self._trans_dwell_s_default if (dwell_s is None) else float(dwell_s)

        def enqueue(shape: str, dt: float, note: str = ""):
            self._mood_queue.append((shape, now + float(dt), note))

        if target == cur:
            return

        if via_neutral and {cur, target} == {"happy", "sad"}:
            enqueue("neutral", self._trans_step_s, "to neutral")
            if dwell and dwell > 0:
                enqueue("neutral", self._trans_step_s + dwell, "dwell neutral")
            enqueue(
                target,
                self._trans_step_s + max(0.0, dwell) + self._trans_step_s,
                f"to {target}",
            )
        else:
            enqueue(target, self._trans_step_s, f"to {target}")

        if (now - self._mood_last_softblink_at) > 0.35:
            self.do(
                "blink",
                duration=self._blink_dur * 0.85,
                hold=self._blink_hold * 0.75,
                max_close=0.55,
            )
            self._mood_last_softblink_at = now

    def is_mood_idle(self) -> bool:
        """True gdy nie ma zaplanowanych kroków zmiany nastroju ust."""
        return not self._mood_queue

    # Polityki
    def _policy_speaking_apply(self) -> None:
        st = self.anim.state
        try:
            st.assist_speaking = bool(self._speaking)
        except Exception:
            pass

        if self._mouth_shape_override in {"happy", "neutral", "sad"}:
            st.mouth.shape = self._mouth_shape_override

        if self._mouth_open_override:
            try:
                st.mouth.open = _clamp01(self._mouth_open_override)
            except Exception:
                pass

        if self._debug_mouth and (time.time() - self._last_dbg) > 1.0:
            cur = getattr(st.mouth, "shape", "?")
            qlen = len(self._mood_queue)
            print(f"[mouth] shape={cur} expr={st.expr} mood={self._mood_current} queue={qlen}")
            self._last_dbg = time.time()

    def _policy_idle_tick(self) -> None:
        if not self.idle:
            return

        now = time.time()

        if now >= self._next_blink_ts:
            self.do("blink", duration=self._blink_dur, hold=self._blink_hold)
            self._schedule_next("blink", self._idle_blink_every)
            self._blink_cooldown_until = now + max(0.18, self._blink_dur * 1.2)
            self._soft_blink_block_until = now + max(0.40, self._blink_dur * 2.5)

            try:
                prob = max(0.0, min(1.0, self._blink_shift_prob))
                if prob > 0.0 and random.random() < prob:
                    self.do("look", t=self._look_t, amp=self._look_amp)
            except Exception:
                pass

        if now >= self._next_soft_blink_ts and now >= self._soft_blink_block_until:
            self.do(
                "blink",
                duration=self._blink_dur * 0.85,
                hold=self._blink_hold * 0.75,
                max_close=0.55,
            )
            self._schedule_next("soft", self._idle_soft_blink_every)
            self._blink_cooldown_until = max(self._blink_cooldown_until, now + 0.12)

        if self._idle_look_every > 0 and now >= self._next_look_ts and now >= self._blink_cooldown_until:
            self.do("look", t=self._look_t, amp=self._look_amp)
            self._schedule_next("look", self._idle_look_every)

        if self._idle_look_p > 0.0 and now >= self._blink_cooldown_until:
            if random.random() < self._idle_look_p:
                self.do("look", t=self._look_t, amp=self._look_amp)

    def _policy_mood_tick(self) -> None:
        if not self._mood_queue:
            return
        now = time.time()
        shape, when_ts, _note = self._mood_queue[0]
        if now >= when_ts:
            self.anim.state.mouth.shape = shape
            self._mood_current = shape
            self._mood_queue.popleft()
            if shape == "neutral" and (now - self._mood_last_softblink_at) > 0.35:
                self.do(
                    "blink",
                    duration=self._blink_dur * 0.75,
                    hold=self._blink_hold * 0.6,
                    max_close=0.55,
                )
                self._mood_last_softblink_at = now

    # Klatki / pętla
    def frame(self) -> bytes:
        st = self.anim.tick()
        self._policy_speaking_apply()
        self._policy_mood_tick()
        self._policy_idle_tick()
        return self.renderer.render_png_bytes(st)

    def frame_image(self) -> Image.Image:
        """Zwraca PIL.Image (używane przez scripts/dev_face-lcd-direct.py)."""
        try:
            data = self.frame()
            return Image.open(BytesIO(data)).convert("RGB")
        except Exception:
            from PIL import ImageDraw

            from apps.draw.face_primitives import draw_face

            st = self.anim.tick()
            self._policy_speaking_apply()
            self._policy_mood_tick()
            self._policy_idle_tick()
            img = Image.new("RGB", (self.size, self.size), (30, 58, 138))
            canvas = ImageDraw.Draw(img)
            draw_face(canvas, {}, st, guide=False, quality="fast")
            return img

    def loop(self, secs: float) -> Iterable[bytes]:
        """Stabilne taktowanie (mniejszy dryf niż zwykłe time.sleep(dt))."""
        dt = 1.0 / max(1, self.fps)
        t_end = time.time() + float(secs)
        t_next = time.time()
        while time.time() < t_end:
            yield self.frame()
            t_next += dt
            to_sleep = t_next - time.time()
            if to_sleep > 0:
                time.sleep(to_sleep)
            else:
                t_next = time.time()
