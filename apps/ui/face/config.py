from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from typing import Any, Dict, Optional

# Python 3.11: tomllib w stdlib; na 3.9/3.10: tomli
try:
    import tomllib  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore
    except Exception:
        tomllib = None  # type: ignore

DEFAULT_PATH = pathlib.Path.home() / ".config" / "rider" / "face.toml"


@dataclass
class FaceConfigAll:
    # Idle / gesty
    idle_enable: bool = True
    idle_blink_sec: float = 3.0
    idle_soft_blink_sec: float = 0.0
    idle_look_p: float = 0.0
    idle_look_sec: float = 0.0
    idle_jitter: float = 0.15
    # Blink
    gesture_blink_dur: float = 0.16
    gesture_blink_hold: float = 0.02
    # Spojrzenie
    gesture_look_t: float = 0.55
    gesture_look_amp: float = 0.42
    # Usta – overrides (kompatybilność)
    mouth_shape: str = ""  # "", "auto", "happy", "neutral", "sad"
    mouth_open: str = ""  # "", lub liczba [0..1] jako string
    # Usta — „małe otwarcie” (wstążka)
    small_th_k_base: float = 0.050
    small_th_k_happy: float = 0.95
    small_th_k_neutral: float = 0.85
    small_th_k_sad: float = 1.05
    # Usta — pozycja Y (ułamki S)
    mouth_y_offset_k_happy: float = 0.040
    mouth_y_offset_k_neutral: float = 0.050
    mouth_y_offset_k_sad: float = 0.050
    # Usta — profil wstążki
    mouth_ribbon_taper_k: float = 0.60
    mouth_ribbon_samples: int = 48
    # Usta — lift/arch
    mouth_happy_lift_k: float = 0.045
    mouth_neutral_lift_k: float = 0.000
    mouth_sad_lift_k: float = -0.045
    mouth_happy_arch_k: float = 0.030
    mouth_neutral_arch_k: float = 0.000
    mouth_sad_arch_k: float = -0.030
    # Przejścia nastroju
    trans_step_s: float = 0.30
    trans_dwell_s: float = 0.18
    mood_interval: float = 1.2
    # Debug
    debug_mouth: bool = False


def _read_toml(path: pathlib.Path) -> Dict[str, Any]:
    if tomllib is None or not path.exists():
        return {}
    with path.open("rb") as f:
        data = tomllib.load(f) or {}
    flat: Dict[str, Any] = {}
    if isinstance(data.get("face"), dict):
        flat.update(data["face"])
    # pozwól też na płaskie klucze na top-level
    for k, v in data.items():
        if isinstance(v, (str, int, float, bool)):
            flat[k] = v
    return flat


def load_config(path: Optional[str | os.PathLike[str]] = None) -> FaceConfigAll:
    p = pathlib.Path(path) if path else pathlib.Path(os.getenv("FACE_CONFIG", DEFAULT_PATH))
    raw = _read_toml(p)
    cfg = FaceConfigAll()
    for k, v in raw.items():
        if hasattr(cfg, k):
            try:
                setattr(cfg, k, v)
            except Exception:
                pass
    _apply_overrides_from_env(cfg)  # ENV > TOML > defaults
    return cfg


def apply_env_from_config(cfg: FaceConfigAll) -> None:
    env_map = {
        # idle
        "FACE_IDLE_ENABLE": "1" if cfg.idle_enable else "0",
        "FACE_IDLE_BLINK_SEC": str(cfg.idle_blink_sec),
        "FACE_IDLE_SOFT_BLINK_SEC": str(cfg.idle_soft_blink_sec),
        "FACE_IDLE_LOOK_P": str(cfg.idle_look_p),
        "FACE_IDLE_LOOK_SEC": str(cfg.idle_look_sec),
        "FACE_IDLE_JITTER": str(cfg.idle_jitter),
        # blink/look
        "FACE_GESTURE_BLINK_DUR": str(cfg.gesture_blink_dur),
        "FACE_GESTURE_BLINK_HOLD": str(cfg.gesture_blink_hold),
        "FACE_GESTURE_LOOK_T": str(cfg.gesture_look_t),
        "FACE_GESTURE_LOOK_AMP": str(cfg.gesture_look_amp),
        # mouth overrides
        "FACE_MOUTH_SHAPE": cfg.mouth_shape,
        "FACE_MOUTH_OPEN": cfg.mouth_open,
        # „małe otwarcie”
        "FACE_MOUTH_SMALL_TH_K_BASE": str(cfg.small_th_k_base),
        "FACE_MOUTH_SMALL_TH_K_HAPPY": str(cfg.small_th_k_happy),
        "FACE_MOUTH_SMALL_TH_K_NEUTRAL": str(cfg.small_th_k_neutral),
        "FACE_MOUTH_SMALL_TH_K_SAD": str(cfg.small_th_k_sad),
        # pozycje Y
        "FACE_MOUTH_Y_OFFSET_K_HAPPY": str(cfg.mouth_y_offset_k_happy),
        "FACE_MOUTH_Y_OFFSET_K_NEUTRAL": str(cfg.mouth_y_offset_k_neutral),
        "FACE_MOUTH_Y_OFFSET_K_SAD": str(cfg.mouth_y_offset_k_sad),
        # profil wstążki
        "FACE_MOUTH_RIBBON_TAPER_K": str(cfg.mouth_ribbon_taper_k),
        "FACE_MOUTH_RIBBON_SAMPLES": str(cfg.mouth_ribbon_samples),
        # lift/arch
        "FACE_MOUTH_HAPPY_LIFT_K": str(cfg.mouth_happy_lift_k),
        "FACE_MOUTH_NEUTRAL_LIFT_K": str(cfg.mouth_neutral_lift_k),
        "FACE_MOUTH_SAD_LIFT_K": str(cfg.mouth_sad_lift_k),
        "FACE_MOUTH_HAPPY_ARCH_K": str(cfg.mouth_happy_arch_k),
        "FACE_MOUTH_NEUTRAL_ARCH_K": str(cfg.mouth_neutral_arch_k),
        "FACE_MOUTH_SAD_ARCH_K": str(cfg.mouth_sad_arch_k),
        # przejścia
        "FACE_TRANS_STEP_S": str(cfg.trans_step_s),
        "FACE_TRANS_DWELL_S": str(cfg.trans_dwell_s),
        "FACE_MOOD_INTERVAL": str(cfg.mood_interval),
        # debug
        "FACE_DEBUG_MOUTH": "1" if cfg.debug_mouth else "0",
    }
    for k, v in env_map.items():
        if os.getenv(k) is None:  # nie nadpisuj, jeśli user podał ręcznie
            os.environ[k] = v


def _apply_overrides_from_env(cfg: FaceConfigAll) -> None:
    def _f(key: str, typ, cur):
        val = os.getenv(key)
        if val is None:
            return cur
        try:
            if typ is bool:
                return val.lower() not in {"0", "false", "no"}
            return typ(val)
        except Exception:
            return cur

    cfg.idle_enable = _f("FACE_IDLE_ENABLE", bool, cfg.idle_enable)
    cfg.mood_interval = _f("FACE_MOOD_INTERVAL", float, cfg.mood_interval)
    cfg.debug_mouth = _f("FACE_DEBUG_MOUTH", bool, cfg.debug_mouth)
