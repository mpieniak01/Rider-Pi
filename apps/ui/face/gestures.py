from __future__ import annotations

from collections.abc import Callable

from .animator import GestureSpec, Keyframe


def blink(duration: float = 0.14) -> GestureSpec:
    """Zamknięcie powiek 0→1→0."""
    return GestureSpec(
        name="blink",
        channel="eyes",
        frames=[
            Keyframe(0.00, {"eyes.blink": 0.0}),
            Keyframe(duration * 0.5, {"eyes.blink": 1.0}),
            Keyframe(duration, {"eyes.blink": 0.0}),
        ],
        fade_in=0.02,
        fade_out=0.02,
    )


def look(dx: float = 0.5, dy: float = 0.0, t: float = 0.25) -> GestureSpec:
    """Przesunięcie spojrzenia."""
    return GestureSpec(
        name="look",
        channel="eyes",
        frames=[
            Keyframe(0.00, {"eyes.dx": 0.0, "eyes.dy": 0.0}),
            Keyframe(t, {"eyes.dx": dx, "eyes.dy": dy}),
        ],
        fade_in=0.04,
        fade_out=0.04,
    )


def nod(t: float = 0.6, amp: float = 0.6) -> GestureSpec:
    """Kiwnięcie głową (na przyszłość — renderer na razie nie używa head.tilt)."""
    return GestureSpec(
        name="nod",
        channel="head",
        frames=[
            Keyframe(0.00, {"head.tilt": 0.0}),
            Keyframe(t * 0.5, {"head.tilt": +amp}),
            Keyframe(t, {"head.tilt": 0.0}),
        ],
        fade_in=0.04,
        fade_out=0.04,
    )


GESTURES: dict[str, Callable[..., GestureSpec]] = {
    "blink": blink,
    "look": look,
    "nod": nod,
}
