from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Head:
    tilt: float = 0.0  # -1..+1 (na przyszłość: "nod"/"shake")


@dataclass
class Eyes:
    dx: float = 0.0  # -1..+1
    dy: float = 0.0  # -1..+1
    blink: float = 0.0  # 0..1


@dataclass
class Brows:
    lift: float = 0.0  # -1..+1
    tilt: float = 0.0  # -1..+1


@dataclass
class Mouth:
    shape: str = "auto"  # "auto" | "happy" | "sad" | "neutral"
    open: float = 0.0  # 0..1 (mowa)


@dataclass
class FaceState:
    expr: str = "happy"
    head: Head = field(default_factory=Head)
    eyes: Eyes = field(default_factory=Eyes)
    brows: Brows = field(default_factory=Brows)
    mouth: Mouth = field(default_factory=Mouth)
