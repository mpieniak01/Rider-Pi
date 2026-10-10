#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import time

from . import compat as C


def _json_or_raw(payload: str):
    try:
        return json.loads(payload) if payload not in (None, "") else None
    except Exception:
        s = (payload or "").strip()
        if s == "":
            return None
        try:
            if "." in s or "e" in s.lower():
                return float(s)
            return int(s)
        except Exception:
            pass
        if "," in s and not s.startswith("{") and not s.startswith("["):
            parts = [p.strip() for p in s.split(",")]
            out = []
            for p in parts:
                try:
                    if "." in p or "e" in p.lower():
                        out.append(float(p))
                    else:
                        out.append(int(p))
                except Exception:
                    out.append(p)
            return out
        return s


def _source_time(value):
    try:
        return value if type(value) in (int, float) and math.isfinite(value) and value > 0 else None
    except OverflowError:
        return None


def _update_xgo_from_dict(d: dict):
    if not isinstance(d, dict):
        return
    observed = _source_time(d.get("observed_at", d.get("ts")))
    C.LAST_XGO.update(
        ts=observed,
        observed_at=observed,
        stale=d.get("stale") is True or observed is None,
        source=d.get("src", d.get("source", "unknown")),
        offline=d.get("offline") is True,
        error=d.get("error"),
    )
    # IMU and battery have independent observation times. A partial IMU must
    # not discard a valid battery reading or make it fresh at API reception.
    incoming_quality = d.get("sensor_quality")
    incoming_quality = incoming_quality if isinstance(incoming_quality, dict) else {}
    incoming_quality = incoming_quality.get("sensors", incoming_quality)
    incoming_quality = incoming_quality if isinstance(incoming_quality, dict) else {}
    quality = dict(C.LAST_XGO.get("sensor_quality", {}))
    times = dict(C.LAST_XGO.get("sensor_observed_at", {}))
    incoming_times = d.get("sensor_observed_at")
    incoming_times = incoming_times if isinstance(incoming_times, dict) else {}
    for key in ("battery_observed_at", "imu_observed_at"):
        carries_value = (
            ("battery_pct" in d or "battery" in d)
            if key == "battery_observed_at"
            else any(axis in d for axis in ("roll", "pitch", "yaw"))
        )
        if key in d and carries_value:
            value = d[key]
            C.LAST_XGO[key] = _source_time(value)
    if "battery_ok" in d and ("battery_pct" in d or "battery" in d):
        C.LAST_XGO["battery_ok"] = d["battery_ok"] if isinstance(d["battery_ok"], bool) else None
    for key in ("imu_ok", "pose", "pose_label", "uart_owner"):
        if key in d:
            C.LAST_XGO[key] = d[key]
    if "battery_pct" in d or "battery" in d:
        value = d.get("battery_pct", d.get("battery"))
        C.LAST_XGO["battery"] = C._sanitize_batt(value) if value is not None else None
    for key in ("roll", "pitch", "yaw"):
        if key in d:
            try:
                value = float(d[key]) if d[key] is not None else None
                if value is not None and not math.isfinite(value):
                    value = None
                if key == "yaw":
                    C.LAST_XGO["yaw_raw"] = value
                C.LAST_XGO[key] = C._norm_angle180(value) if key == "yaw" and value is not None else value
            except (TypeError, ValueError, OverflowError):
                C.LAST_XGO[key] = None
                if key == "yaw":
                    C.LAST_XGO["yaw_raw"] = None
    for name in ("roll", "pitch", "yaw", "battery"):
        present = ("battery_pct" in d or "battery" in d) if name == "battery" else name in d
        if not present:
            continue
        # imu.data also carries battery metadata, but no battery value. Never
        # attach a newer timestamp to the cached value from devices.xgo.
        row = incoming_quality.get(name)
        row = dict(row) if isinstance(row, dict) else None
        key = "battery_observed_at" if name == "battery" else "imu_observed_at"
        at = (
            row["observed_at"]
            if row is not None and "observed_at" in row
            else incoming_times[name]
            if name in incoming_times
            else d[key]
            if key in d
            else observed
        )
        at = _source_time(at)
        value = C.LAST_XGO.get("battery" if name == "battery" else name)
        ready = value is not None and at is not None and d.get("offline") is not True and not d.get("error")
        ready = ready and (
            row.get("ready") is True
            if row is not None
            else d.get("stale") is not True
            and (d.get("battery_ok") is not False if name == "battery" else d.get("imu_ok") is not False)
        )
        if row is not None:
            ready = ready and not row.get("error") and row.get("offline") is not True and row.get("stale") is not True
        times[name] = at
        quality[name] = {
            **(row or {}),
            "ready": bool(ready),
            "observed_at": at,
            "source": (row or {}).get("source", C.LAST_XGO["source"]),
        }
        if name == "battery":
            C.LAST_XGO["battery_observed_at"] = at
            C.LAST_XGO["battery_ok"] = bool(ready)
    C.LAST_XGO["sensor_quality"] = quality
    C.LAST_XGO["sensor_observed_at"] = times
    axis_times = [times.get(name) for name in ("roll", "pitch", "yaw")]
    C.LAST_XGO["imu_observed_at"] = min(axis_times) if all(at is not None for at in axis_times) else None
    if "fw" in d:
        C.XGO_FW = C._sanitize_fw(d["fw"])


def observe_xgo(topic: str, data: object) -> bool:
    """Project source measurements, never timestamp missing data at reception."""
    prefixes = ("devices.xgo", "xgo", "motion.bridge.telemetry")
    prefix = next((value for value in prefixes if topic == value or topic.startswith(value + ".")), None)
    if topic == "imu.data":
        row = dict(data) if isinstance(data, dict) else {}
    elif prefix is None:
        if topic != "motion.bridge.battery_pct":
            return False
        row = dict(data) if isinstance(data, dict) else {"battery_pct": data}
    else:
        suffix = topic[len(prefix) :].lstrip(".")
        if not suffix:
            row = dict(data) if isinstance(data, dict) else {}
        elif isinstance(data, dict) and any(key in data for key in (suffix, "value", "observed_at", "ts")):
            row = dict(data)
            row[suffix] = data.get(suffix, data.get("value"))
        else:
            row = {suffix: data}
    _update_xgo_from_dict(row)
    if "yaw_src" in row:
        C.LAST_XGO["yaw_src"] = row["yaw_src"]
    if topic == "imu.data":
        axes = {axis: C.LAST_XGO.get(axis) for axis in ("roll", "pitch", "yaw")}
        C.LAST_XGO["pose"] = {"x": axes["roll"], "y": axes["pitch"], "z": axes["yaw"]}
        C.LAST_XGO["pose_label"] = C._classify_pose(axes["roll"], axes["pitch"])
    return True


def observe_navigator(data: object) -> None:
    """Keep producer state and request identity; transport receipt is no ACK."""
    if not isinstance(data, dict):
        return
    from .navigation_state import observe_plan

    C.LAST_NAVIGATOR.update(observe_plan(data))
    fields = (
        "active",
        "state",
        "strategy",
        "obstacle_present",
        "generation",
        "request_id",
        "accepted",
        "data_ready",
        "navigation_ready",
        "data_error",
        "reason",
    )
    for key in fields:
        if key in data:
            C.LAST_NAVIGATOR[key] = data[key]
    observed = data.get("observed_at", data.get("ts"))
    try:
        if type(observed) not in (int, float) or not math.isfinite(observed) or observed <= 0:
            observed = None
    except OverflowError:
        observed = None
    C.LAST_NAVIGATOR.update(
        ts=observed,
        observed_at=observed,
        source=data.get("source", "navigator.state"),
        stale=data.get("stale") is True or observed is None,
    )


def _decode_frames(frames):
    if not frames:
        return "", ""
    if len(frames) == 1:
        s = frames[0]
        return (s.split(" ", 1) + [""])[:2] if " " in s else (s, "")
    topic = frames[0]
    payload = frames[1] if len(frames) == 2 else " ".join(frames[1:])
    return topic, payload


def observe_lcd(data: dict) -> None:
    """A renderer report can describe power; descriptor ownership cannot."""
    if not isinstance(data, dict):
        return
    lcd = data.get("lcd")
    if not isinstance(lcd, dict):
        return
    state = C.LAST_CAMERA["lcd"]
    for key in ("enabled_env", "no_draw", "rot", "active", "presenting"):
        if key in lcd:
            state[key] = lcd[key]
    if isinstance(lcd.get("active"), bool):
        state["presenting"] = lcd["active"]
    if "on" in lcd:
        state["on"] = lcd["on"] if isinstance(lcd["on"], bool) else None
        state["power_known"] = isinstance(lcd["on"], bool)
        state["power_source"] = "camera.heartbeat"
        state["power_observed_at"] = data.get("observed_at", data.get("ts"))


def bus_sub_loop():
    try:
        import zmq
    except Exception:
        print("[api] pyzmq not available – bus features disabled", flush=True)
        return
    try:
        ctx = zmq.Context.instance()
        sub = ctx.socket(zmq.SUB)
        sub.connect(f"tcp://127.0.0.1:{C.BUS_SUB_PORT}")
        for t in (
            "vision.",
            "camera.",
            "motion.bridge.",
            "motion.",
            "cmd.",
            "devices.",
            "xgo.",
            "tracking.",
            "navigator.",
            "robot.pose",
            "mapper.map.data",
            "imu.data",
        ):
            sub.setsockopt_string(zmq.SUBSCRIBE, t)
        try:
            sub.setsockopt(zmq.RCVTIMEO, 1000)
        except Exception:
            pass
        print(f"[api] SUB connected tcp://127.0.0.1:{C.BUS_SUB_PORT}", flush=True)

        while True:
            try:
                try:
                    parts_bin = sub.recv_multipart(flags=0)
                except zmq.Again:
                    continue
                frames = [p.decode("utf-8", "ignore") for p in parts_bin]
                topic, payload = _decode_frames(frames)

                C.LAST_MSG_TS = time.time()
                C.EVENTS.append({"ts": C.LAST_MSG_TS, "topic": topic, "data": payload})
                if topic in {"robot.pose", "mapper.map.data", "navigator.path"}:
                    from .navigation_state import observe

                    observe(topic, _json_or_raw(payload))

                if topic == "vision.dispatcher.heartbeat":
                    C.LAST_HEARTBEAT_TS = C.LAST_MSG_TS
                    continue

                if observe_xgo(topic, _json_or_raw(payload)):
                    continue

                if topic == "vision.state":
                    try:
                        data = json.loads(payload) if payload else {}
                        C.LAST_STATE["present"] = bool(data.get("present", C.LAST_STATE["present"]))
                        C.LAST_STATE["confidence"] = float(data.get("confidence", C.LAST_STATE["confidence"]))
                        if "mode" in data:
                            C.LAST_STATE["mode"] = data.get("mode")
                        C.LAST_STATE["ts"] = float(data.get("ts", C.LAST_MSG_TS))
                    except Exception:
                        pass
                    continue

                if topic == "camera.heartbeat":
                    try:
                        data = json.loads(payload) if payload else {}
                        C.LAST_CAMERA["ts"] = C.LAST_MSG_TS
                        C.LAST_CAMERA["mode"] = data.get("mode")
                        C.LAST_CAMERA["fps"] = data.get("fps")
                        lcd_state = C.LAST_CAMERA["lcd"]
                        lcd_state.update(
                            {
                                "enabled_env": (not C.ENV_DISABLE_LCD),
                                "no_draw": C.ENV_NO_DRAW,
                                "rot": C.ENV_ROT,
                                "checked_at": C.LAST_MSG_TS,
                            }
                        )
                        observe_lcd(data)
                    except Exception:
                        pass
                    continue

                if topic == "cmd.balance":
                    data = _json_or_raw(payload)
                    enabled = None
                    if isinstance(data, dict):
                        enabled = data.get("enabled")
                    elif isinstance(data, (int, float, bool)):
                        enabled = bool(data)
                    if enabled is not None:
                        C.LAST_BALANCE["enabled"] = bool(enabled)
                        C.LAST_BALANCE["ts"] = C.LAST_MSG_TS
                    continue

                if topic == "cmd.height":
                    data = _json_or_raw(payload)
                    height_val = None
                    if isinstance(data, dict):
                        height_val = data.get("height")
                    elif isinstance(data, (int, float)):
                        height_val = data
                    if height_val is not None:
                        try:
                            height_int = int(height_val)
                        except Exception:
                            height_int = None
                        if height_int is not None:
                            height_int = max(0, min(12, height_int))
                            C.LAST_HEIGHT["value"] = height_int
                            C.LAST_HEIGHT["ts"] = C.LAST_MSG_TS
                    continue

                if topic == "tracking.mode:set":
                    data = _json_or_raw(payload)
                    mode = None
                    if isinstance(data, dict):
                        mode = data.get("mode")
                    elif isinstance(data, str):
                        mode = data
                    mode_str = "none" if mode is None else str(mode)
                    mode_norm = mode_str.strip().lower() or "none"
                    C.LAST_TRACKING_MODE["mode"] = mode_norm
                    C.LAST_TRACKING_MODE["enabled"] = mode_norm in ("face", "hand")
                    C.LAST_TRACKING_MODE["ts"] = C.LAST_MSG_TS
                    continue

                if topic == "vision.tracking.offset":
                    data = _json_or_raw(payload)
                    if isinstance(data, dict):
                        offset = data.get("offset_x")
                        try:
                            offset = None if offset is None else float(offset)
                        except Exception:
                            offset = None
                        if offset is not None:
                            C.LAST_TRACKING_OFFSET["offset"] = offset
                        else:
                            C.LAST_TRACKING_OFFSET["offset"] = None
                        if "mode" in data and data.get("mode") is not None:
                            C.LAST_TRACKING_OFFSET["mode"] = data.get("mode")
                        ts_val = data.get("ts") or C.LAST_MSG_TS or time.time()
                        try:
                            C.LAST_TRACKING_OFFSET["ts"] = float(ts_val)
                        except Exception:
                            C.LAST_TRACKING_OFFSET["ts"] = time.time()
                    continue

                if topic == "navigator.state":
                    observe_navigator(_json_or_raw(payload))
                    continue

            except Exception:
                time.sleep(0.05)
    except Exception as e:
        print(f"[api] bus_sub_loop error: {e}", flush=True)


def xgo_ro_loop():
    """Legacy read-only entry uses the shared telemetry bus, never opens UART."""
    C.start_bus_sub()
