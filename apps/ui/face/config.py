# apps/ui/face/config.py
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from typing import Any

# Python 3.11: tomllib; 3.9/3.10: tomli
try:
    import tomllib  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore
    except Exception:  # pragma: no cover
        tomllib = None  # type: ignore

DEFAULT_PATH = pathlib.Path.home() / ".config" / "rider" / "face.toml"
LEGACY_REPO_PATH = pathlib.Path("apps/ui/face/face.toml")  # deprecated
REPO_PATH = pathlib.Path("config/face.toml")


@dataclass
class FaceConfigAll:
    # Splash configuration
    vendor_splash_logo_path: str = "/home/pi/robot/data/splash_logo.png"
    splash_lcd_rotate: int = 270
    # Idle / gestures
    idle_enable: bool = True
    idle_blink_sec: float = 3.0
    idle_soft_blink_sec: float = 0.0
    idle_look_p: float = 0.0
    idle_look_sec: float = 0.0
    idle_jitter: float = 0.15
    # Blink
    gesture_blink_dur: float = 0.16
    gesture_blink_hold: float = 0.02
    # Look
    gesture_look_t: float = 0.55
    gesture_look_amp: float = 0.42
    # Mouth overrides (compat)
    mouth_shape: str = ""  # "", "auto", "happy", "neutral", "sad"
    mouth_open: str = ""  # "", or numeric [0..1] as string
    # Mouth — small opening (ribbon)
    small_th_k_base: float = 0.050
    small_th_k_happy: float = 0.95
    small_th_k_neutral: float = 0.85
    small_th_k_sad: float = 1.05
    # Mouth — Y offsets
    mouth_y_offset_k_happy: float = 0.040
    mouth_y_offset_k_neutral: float = 0.050
    mouth_y_offset_k_sad: float = 0.050
    # Mouth — ribbon profile
    mouth_ribbon_taper_k: float = 0.60
    mouth_ribbon_samples: int = 48
    # Mouth — lift/arch
    mouth_happy_lift_k: float = 0.045
    mouth_neutral_lift_k: float = 0.000
    mouth_sad_lift_k: float = -0.045
    mouth_happy_arch_k: float = 0.030
    mouth_neutral_arch_k: float = 0.000
    mouth_sad_arch_k: float = -0.030
    # Transitions
    trans_step_s: float = 0.30
    trans_dwell_s: float = 0.18
    mood_interval: float = 1.2
    # Debug
    debug_mouth: bool = False


def _discover_path(cli_or_env: str | os.PathLike[str] | None) -> pathlib.Path:
    """Search order:
    1) FACE_CONFIG
    2) $RIDER_CONFIG_DIR/face.toml
    3) ./config/face.toml
    4) legacy apps/ui/face/face.toml
    5) ~/.config/rider/face.toml
    """
    if cli_or_env:
        p = pathlib.Path(cli_or_env)
        if p.exists():
            return p

    rid = os.getenv("RIDER_CONFIG_DIR")
    if rid:
        p = pathlib.Path(rid) / "face.toml"
        if p.exists():
            return p

    if REPO_PATH.exists():
        return REPO_PATH

    if LEGACY_REPO_PATH.exists():
        print("[face.config] WARNING: using legacy apps/ui/face/face.toml (DEPRECATED)")
        return LEGACY_REPO_PATH

    return DEFAULT_PATH


def _read_toml(path: pathlib.Path) -> dict[str, Any]:
    if tomllib is None or not path.exists():
        return {}
    with path.open("rb") as f:
        data = tomllib.load(f) or {}
    if not isinstance(data, dict):
        return {}

    # Accept both:
    # 1) flat keys at top-level (old style),
    # 2) nested under [face], and sub-sections per new schema.
    flat: dict[str, Any] = {}

    # 2. nested under "face"
    face = data.get("face")
    if isinstance(face, dict):
        _import_face_section(flat, face)

    # 1. also allow flat top-level primitives
    for k, v in data.items():
        if isinstance(v, (str, int, float, bool)):
            flat[k] = v

    return flat


def _import_face_section(out: dict[str, Any], f: dict[str, Any]) -> None:
    """
    Map nested structure like:
      [face.idle], [face.gesture.blink], [face.gesture.look],
      [face.mouth.small_th_k], [face.mouth.offsets], [face.mouth.ribbon],
      [face.mouth.lift], [face.mouth.arch], [face.transitions], [face.debug]
    into FaceConfigAll field names.
    """
    # [face.idle]
    idle = f.get("idle")
    if isinstance(idle, dict):
        _copy_num(idle, out, "blink_sec", "idle_blink_sec")
        _copy_num(idle, out, "soft_blink_sec", "idle_soft_blink_sec")
        _copy_num(idle, out, "look_p", "idle_look_p")
        _copy_num(idle, out, "look_sec", "idle_look_sec")
        _copy_num(idle, out, "jitter", "idle_jitter")
        _copy_bool(idle, out, "enable", "idle_enable")

    # [face.gesture.blink]
    gest = f.get("gesture")
    if isinstance(gest, dict):
        blink = gest.get("blink")
        if isinstance(blink, dict):
            _copy_num(blink, out, "dur", "gesture_blink_dur")
            _copy_num(blink, out, "hold", "gesture_blink_hold")
        look = gest.get("look")
        if isinstance(look, dict):
            _copy_num(look, out, "t", "gesture_look_t")
            _copy_num(look, out, "amp", "gesture_look_amp")

    # [face.mouth.small_th_k]
    mouth = f.get("mouth")
    if isinstance(mouth, dict):
        stk = mouth.get("small_th_k")
        if isinstance(stk, dict):
            _copy_num(stk, out, "base", "small_th_k_base")
            _copy_num(stk, out, "happy", "small_th_k_happy")
            _copy_num(stk, out, "neutral", "small_th_k_neutral")
            _copy_num(stk, out, "sad", "small_th_k_sad")

        offs = mouth.get("offsets")
        if isinstance(offs, dict):
            _copy_num(offs, out, "y_offset_k_happy", "mouth_y_offset_k_happy")
            _copy_num(offs, out, "y_offset_k_neutral", "mouth_y_offset_k_neutral")
            _copy_num(offs, out, "y_offset_k_sad", "mouth_y_offset_k_sad")

        rib = mouth.get("ribbon")
        if isinstance(rib, dict):
            _copy_num(rib, out, "taper_k", "mouth_ribbon_taper_k")
            _copy_num(rib, out, "samples", "mouth_ribbon_samples")

        lift = mouth.get("lift")
        if isinstance(lift, dict):
            _copy_num(lift, out, "happy", "mouth_happy_lift_k")
            _copy_num(lift, out, "neutral", "mouth_neutral_lift_k")
            _copy_num(lift, out, "sad", "mouth_sad_lift_k")

        arch = mouth.get("arch")
        if isinstance(arch, dict):
            _copy_num(arch, out, "happy", "mouth_happy_arch_k")
            _copy_num(arch, out, "neutral", "mouth_neutral_arch_k")
            _copy_num(arch, out, "sad", "mouth_sad_arch_k")

    # [face.transitions]
    trans = f.get("transitions")
    if isinstance(trans, dict):
        _copy_num(trans, out, "step_s", "trans_step_s")
        _copy_num(trans, out, "dwell_s", "trans_dwell_s")

    # [face.debug]
    dbg = f.get("debug")
    if isinstance(dbg, dict):
        _copy_bool(dbg, out, "mouth", "debug_mouth")


def _copy_num(src: dict[str, Any], dst: dict[str, Any], key: str, out_key: str) -> None:
    v = src.get(key)
    if isinstance(v, (int, float)):
        dst[out_key] = float(v)


def _copy_bool(src: dict[str, Any], dst: dict[str, Any], key: str, out_key: str) -> None:
    v = src.get(key)
    if isinstance(v, bool):
        dst[out_key] = v
    elif isinstance(v, (int, float)):
        dst[out_key] = bool(v)


def load_config(path: str | os.PathLike[str | None] = None) -> FaceConfigAll:
    p = _discover_path(path or os.getenv("FACE_CONFIG"))
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
        # small opening
        "FACE_MOUTH_SMALL_TH_K_BASE": str(cfg.small_th_k_base),
        "FACE_MOUTH_SMALL_TH_K_HAPPY": str(cfg.small_th_k_happy),
        "FACE_MOUTH_SMALL_TH_K_NEUTRAL": str(cfg.small_th_k_neutral),
        "FACE_MOUTH_SMALL_TH_K_SAD": str(cfg.small_th_k_sad),
        # Y offsets
        "FACE_MOUTH_Y_OFFSET_K_HAPPY": str(cfg.mouth_y_offset_k_happy),
        "FACE_MOUTH_Y_OFFSET_K_NEUTRAL": str(cfg.mouth_y_offset_k_neutral),
        "FACE_MOUTH_Y_OFFSET_K_SAD": str(cfg.mouth_y_offset_k_sad),
        # ribbon profile
        "FACE_MOUTH_RIBBON_TAPER_K": str(cfg.mouth_ribbon_taper_k),
        "FACE_MOUTH_RIBBON_SAMPLES": str(cfg.mouth_ribbon_samples),
        # lift/arch
        "FACE_MOUTH_HAPPY_LIFT_K": str(cfg.mouth_happy_lift_k),
        "FACE_MOUTH_NEUTRAL_LIFT_K": str(cfg.mouth_neutral_lift_k),
        "FACE_MOUTH_SAD_LIFT_K": str(cfg.mouth_sad_lift_k),
        "FACE_MOUTH_HAPPY_ARCH_K": str(cfg.mouth_happy_arch_k),
        "FACE_MOUTH_NEUTRAL_ARCH_K": str(cfg.mouth_neutral_arch_k),
        "FACE_MOUTH_SAD_ARCH_K": str(cfg.mouth_sad_arch_k),
        # transitions
        "FACE_TRANS_STEP_S": str(cfg.trans_step_s),
        "FACE_TRANS_DWELL_S": str(cfg.trans_dwell_s),
        "FACE_MOOD_INTERVAL": str(cfg.mood_interval),
        # debug
        "FACE_DEBUG_MOUTH": "1" if cfg.debug_mouth else "0",
    }
    for k, v in env_map.items():
        if os.getenv(k) is None:  # don't overwrite when user set manually
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
