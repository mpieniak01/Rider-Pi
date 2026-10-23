"""Bounded per-model semantic interpretation; Pi persists the same wire schema."""

from __future__ import annotations

import math

SEMANTIC_MODELS = ("segformer-b0-ade20k", "yolo26n-sem-ade20k")
LIMITS = {
    "pixel_confidence": (0.05, 1.0),
    "min_floor_fraction": (0.5, 1.0),
    "max_uncertain_fraction": (0.0, 0.5),
    "min_region_fraction": (0.0, 0.02),
}
LEGACY_SEMANTIC = {
    "pixel_confidence": 0.8,
    "min_floor_fraction": 1.0,
    "max_uncertain_fraction": 0.01,
    "min_region_fraction": 0.0,
    "thin_span_fraction": 0.15,
    "near_zone_fraction": 0.35,
    "min_near_floor_fraction": 1.0,
}


def active_model_id(perception):
    model = perception.get("model_id")
    if model:
        return model
    return "depth-anything-v2-indoor-small" if perception.get("engine") == "depth_plane" else SEMANTIC_MODELS[0]


def validate_semantic_models(value):
    if not isinstance(value, dict) or set(value) - set(SEMANTIC_MODELS):
        raise ValueError("navigation_model_tuning_invalid")
    result = {}
    for model, settings in value.items():
        if (
            not isinstance(settings, dict)
            or set(settings) - {"version", "surface", *LIMITS}
            or type(settings.get("version", 1)) is not int
            or settings.get("version", 1) != 1
            or settings.get("surface", "floor_only") not in ("floor_only", "floor_rug")
        ):
            raise ValueError("navigation_model_tuning_invalid")
        row = {"version": 1, "surface": settings.get("surface", "floor_only")}
        for name, (low, high) in LIMITS.items():
            number = settings.get(name)
            if number is not None and (
                isinstance(number, bool)
                or not isinstance(number, (int, float))
                or not math.isfinite(number)
                or not low <= number <= high
            ):
                raise ValueError("navigation_model_tuning_invalid")
            row[name] = number
        result[model] = row
    return result


def has_semantic_tuning(perception, model_id=None):
    model = model_id or active_model_id(perception)
    return model in validate_semantic_models(perception.get("semantic_models", {}))


def semantic_parameters(perception, behavior=None, model_id=None):
    from services.navigation_profiles import DEFAULT_BEHAVIOR, parameters

    model = model_id or active_model_id(perception)
    if model not in SEMANTIC_MODELS:
        raise ValueError("navigation_model_tuning_unsupported")
    settings = validate_semantic_models(perception.get("semantic_models", {})).get(model, {})
    resolved = {**LEGACY_SEMANTIC, **parameters(behavior or DEFAULT_BEHAVIOR)}
    for name in LIMITS:
        if settings.get(name) is not None:
            resolved[name] = settings[name]
    resolved["traversable_labels"] = [3, 28] if settings.get("surface") == "floor_rug" else [3]
    return validate_resolved_semantic(resolved)


def validate_resolved_semantic(value):
    if not isinstance(value, dict):
        raise ValueError("navigation_model_tuning_invalid")
    labels = value.get("traversable_labels")
    if (
        not isinstance(labels, (list, tuple))
        or tuple(labels) not in ((3,), (3, 28))
        or any(type(label) is not int for label in labels)
    ):
        raise ValueError("navigation_model_tuning_invalid")
    for name in LEGACY_SEMANTIC:
        number = value.get(name)
        low, high = LIMITS.get(name, (0.0, 1.0))
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(number)
            or not low <= number <= high
            or name in ("thin_span_fraction", "near_zone_fraction")
            and number <= 0
        ):
            raise ValueError("navigation_model_tuning_invalid")
    return {**value, "traversable_labels": list(labels)}


def presentation(config):
    perception = config.get("perception", {})
    model = active_model_id(perception)
    configured = validate_semantic_models(perception.get("semantic_models", {})).get(model, {})
    effective = (
        semantic_parameters(perception, config.get("behavior"), model)
        if model in SEMANTIC_MODELS
        else {
            name: perception.get(name, default)
            for name, default in (
                ("residual_limit", 0.06),
                ("outlier_limit", 0.005),
                ("slope_min", 2.0),
            )
        }
    )
    return {
        "version": 1,
        "active_model_id": model,
        "configured": configured,
        "effective": effective,
    }
