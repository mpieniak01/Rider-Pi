from __future__ import annotations

from dataclasses import dataclass, field

# --- helpers -----------------------------------------------------------------


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


def _clamp11(x: float) -> float:
    try:
        x = float(x)
    except Exception:
        return 0.0
    if x < -1.0:
        return -1.0
    if x > 1.0:
        return 1.0
    return x


# w klasie FaceState:
def blink_mul(self) -> float:
    b = float(getattr(self.eyes, "blink", 0.0))
    if b < 0.0:
        b = 0.0
    if b > 1.0:
        b = 1.0
    mul = 1.0 - b
    return 0.06 if mul < 0.06 else mul


# --- state dataclasses --------------------------------------------------------


@dataclass
class Head:
    tilt: float = 0.0  # -1..+1 (na przyszłość: "nod"/"shake")

    def tilt_clamped(self) -> float:
        return _clamp11(self.tilt)


@dataclass
class Eyes:
    dx: float = 0.0  # -1..+1
    dy: float = 0.0  # -1..+1
    blink: float = 0.0  # 0..1

    def gaze(self) -> tuple[float, float]:
        """Zwraca skorygowane odchylenie źrenicy (dx, dy) w zakresie [-1, 1]."""
        return _clamp11(self.dx), _clamp11(self.dy)

    def blink_level(self) -> float:
        """Surowy poziom mrugnięcia (0..1), dla zgodności jeśli gdzieś używasz bezpośrednio."""
        return _clamp01(self.blink)


@dataclass
class Brows:
    lift: float = 0.0  # -1..+1
    tilt: float = 0.0  # -1..+1

    def lift_clamped(self) -> float:
        return _clamp11(self.lift)

    def tilt_clamped(self) -> float:
        return _clamp11(self.tilt)


@dataclass
class Mouth:
    shape: str = "auto"  # "auto" | "happy" | "sad" | "neutral"
    open: float = 0.0  # 0..1 (mowa)

    def open_clamped(self) -> float:
        return _clamp01(self.open)


@dataclass
class FaceState:
    expr: str = "happy"
    head: Head = field(default_factory=Head)
    eyes: Eyes = field(default_factory=Eyes)
    brows: Brows = field(default_factory=Brows)
    mouth: Mouth = field(default_factory=Mouth)

    # --- kompatybilność z rendererem/legacy ----------------------------------
    def blink_mul(self) -> float:
        """
        Skala wysokości oka używana przez renderer:
          1.0  → oko otwarte
          ~0.0 → oko zamknięte
        Animator ustawia Eyes.blink w 0..1. Dodajemy minimalny „prześwit”,
        żeby oko nie znikało całkowicie na niektórych panelach.
        """
        b = self.eyes.blink_level()  # 0..1
        mul = 1.0 - b  # 1..0
        # zostaw delikatny prześwit; tunowalne jeśli chcesz
        return 0.06 if mul < 0.06 else mul

    # (opcjonalnie) mapping auto-ust dla ust wg expr; zostawiam wyłączone,
    # bo nie było tego w starym API. Jeśli kiedyś zechcesz:
    # def resolve_mouth_shape(self) -> str:
    #     if self.mouth.shape != "auto":
    #         return self.mouth.shape
    #     return {"happy": "happy", "sad": "sad"}.get(self.expr, "neutral")
