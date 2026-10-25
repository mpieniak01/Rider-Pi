"""Device-owned DA2 input bounds. Saving never starts inference."""

import math

DA2 = "depth-anything-v2-indoor-small"
RECOMMENDED = {"version": 1, "bounds": [0.0, 0.4, 1.0, 1.0]}


def validate_input_region(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "bounds"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or not isinstance(value["bounds"], list)
        or len(value["bounds"]) != 4
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in value["bounds"])
    ):
        raise ValueError("navigation_input_region_invalid")
    a, b, c, d = value["bounds"]
    if not 0 <= a < c <= 1 or not 0 <= b < d <= 1:
        raise ValueError("navigation_input_region_invalid")
    return value


def validate_input_policy(config):
    perception = config["perception"]
    value = perception.get("input_region")
    if value is None:
        if "input_region" in perception:
            raise ValueError("navigation_input_region_invalid")
        return
    validate_input_region(value)
    if perception["engine"] != "depth_plane" or perception.get("model_id", DA2) not in ("", DA2):
        raise ValueError("navigation_input_region_unsupported")
    a, b, c, d = value["bounds"]
    x0, y0, x1, y1 = config["corridor"]
    top = min(y0, max(0.0, round(y1 - 0.30, 12)))
    if not (a <= x0 and b <= top and c >= x1 and d >= y1):
        raise ValueError("navigation_input_region_excludes_reference")
    geometry = config.get("avoidance", {}).get("geometry", {})
    if (
        config.get("avoidance", {}).get("enabled")
        and geometry.get("mode") == "ground"
        and value["bounds"] != [0, 0, 1, 1]
    ):
        raise ValueError("navigation_input_region_requires_image_geometry")
