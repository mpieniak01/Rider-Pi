"""Shared graphic gesture contract. Values never describe physical motion."""

import math

CONTRACT = "rider.face"
VERSION = 1
MAX_AUTHORED_DURATION_S = 10
MAX_PLAYBACK_DURATION_S = 20
FIELDS = {
    "eyes.dx": (-1, 1),
    "eyes.dy": (-1, 1),
    "eyes.blink": (0, 1),
    "brows.lift": (-1, 1),
    "brows.tilt": (-1, 1),
    "mouth.open": (0, 1),
    "mouth.curve": (-1, 1),
}
MOODS = {
    "neutral": {"mouth.curve": 0.15},
    "calm": {"mouth.curve": 0.25, "brows.lift": 0.05},
    "happy": {"mouth.curve": 0.8, "brows.lift": 0.3},
    "sad": {"mouth.curve": -0.65, "brows.tilt": -0.35},
    "curious": {"eyes.dx": 0.35, "eyes.dy": -0.15, "brows.lift": 0.45, "brows.tilt": 0.5, "mouth.curve": 0.25},
    "surprised": {"brows.lift": 0.75, "mouth.open": 0.6, "mouth.curve": 0},
    "sleepy": {"eyes.blink": 0.65, "brows.lift": -0.25, "mouth.curve": 0.1},
}
EXPRESSIONS = set(MOODS)
EASING = {"lin", "in", "out", "in_out"}


def number(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid_number")
    value = float(value)
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError("value_out_of_range")
    return value


def validate(body):
    if not isinstance(body, dict):
        raise ValueError("invalid_gesture")
    name = body.get("name", "")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
        raise ValueError("name_required")
    expr = body.get("expr", "neutral")
    if not isinstance(expr, str) or expr not in EXPRESSIONS:
        raise ValueError("invalid_expression")
    version = body.get("contract_version", VERSION)
    if type(version) is not int or version != VERSION:
        raise ValueError("unsupported_face_contract")
    duration = number(body.get("duration", 1), 0.05, MAX_AUTHORED_DURATION_S)
    initial, tracks = body.get("initial", {}), body.get("tracks", {})
    if not isinstance(initial, dict) or not isinstance(tracks, dict):
        raise ValueError("invalid_tracks")
    clean_initial, clean_tracks = {}, {}
    for field, value in initial.items():
        if field not in FIELDS:
            raise ValueError("invalid_field")
        clean_initial[field] = number(value, *FIELDS[field])
    for field, segments in tracks.items():
        if field not in FIELDS or not isinstance(segments, list) or len(segments) > 32:
            raise ValueError("invalid_track")
        clean_tracks[field] = []
        end = 0
        for segment in segments:
            if not isinstance(segment, dict):
                raise ValueError("invalid_segment")
            t0, t1 = number(segment["t0"], end, duration), number(segment["t1"], 0, duration)
            ease = segment.get("ease", "lin")
            if t1 <= t0 or not isinstance(ease, str) or ease not in EASING:
                raise ValueError("invalid_segment")
            clean_tracks[field].append(
                {
                    "t0": t0,
                    "t1": t1,
                    "v0": number(segment["v0"], *FIELDS[field]),
                    "v1": number(segment["v1"], *FIELDS[field]),
                    "ease": ease,
                }
            )
            end = t1
    return {
        "name": name.strip(),
        "expr": expr,
        "duration": duration,
        "initial": clean_initial,
        "tracks": clean_tracks,
        "contract_version": VERSION,
    }


def prepare(spec, intensity=1, tempo=1, transition="original", *, defaults=False):
    spec = validate(spec)
    intensity, tempo = number(intensity, 0, 1), number(tempo, 0.5, 2)
    if transition not in EASING | {"original"}:
        raise ValueError("invalid_transition")
    spec["duration"] /= tempo
    if defaults:
        spec["initial"] = {**dict.fromkeys(FIELDS, 0.0), **MOODS[spec["expr"]], **spec["initial"]}
    spec["initial"] = {key: value * intensity for key, value in spec["initial"].items()}
    for segments in spec["tracks"].values():
        for segment in segments:
            segment["t0"] /= tempo
            segment["t1"] /= tempo
            segment["v0"] *= intensity
            segment["v1"] *= intensity
            if transition != "original":
                segment["ease"] = transition
    return spec
