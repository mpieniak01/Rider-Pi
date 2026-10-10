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


def _update_xgo_from_dict(d: dict):
    if not isinstance(d, dict):
        return
    observed = d.get("observed_at", d.get("ts"))
    C.LAST_XGO.update(
        ts=observed,
        observed_at=observed,
        stale=d.get("stale", observed is None),
        source=d.get("src", d.get("source", "unknown")),
    )
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
                C.LAST_XGO[key] = C._norm_angle180(value) if key == "yaw" and value is not None else value
            except (TypeError, ValueError):
                C.LAST_XGO[key] = None
    if "fw" in d:
        C.XGO_FW = C._sanitize_fw(d["fw"])


def _decode_frames(frames):
    if not frames:
        return "", ""
    if len(frames) == 1:
        s = frames[0]
        return (s.split(" ", 1) + [""])[:2] if " " in s else (s, "")
    topic = frames[0]
    payload = frames[1] if len(frames) == 2 else " ".join(frames[1:])
    return topic, payload


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

                if topic == "vision.dispatcher.heartbeat":
                    C.LAST_HEARTBEAT_TS = C.LAST_MSG_TS
                    continue

                if topic.startswith("devices.xgo"):
                    suffix = topic[len("devices.xgo") :].lstrip(".")
                    data = _json_or_raw(payload)
                    if suffix == "" and isinstance(data, dict):
                        _update_xgo_from_dict(data)
                    else:
                        C.LAST_XGO["ts"] = C.LAST_MSG_TS
                        if suffix == "pose":
                            if data not in (None, "", []):
                                C.LAST_XGO["pose"] = data
                        elif suffix == "pose_label":
                            if data not in (None, "", []):
                                C.LAST_XGO["pose_label"] = data
                        elif suffix in ("battery", "battery_pct"):
                            b = C._sanitize_batt(data) if data is not None else None
                            if b is not None:
                                C.LAST_XGO["battery"] = b
                        elif suffix in ("roll", "pitch", "yaw"):
                            try:
                                v = float(data) if data is not None else None
                                if v is not None:
                                    if suffix == "yaw":
                                        v = C._norm_angle180(v)
                                    prev = C.LAST_XGO.get(suffix)
                                    if (v == 0.0) and (prev not in (None, 0.0)):
                                        pass
                                    else:
                                        C.LAST_XGO[suffix] = v
                            except Exception:
                                C.LAST_XGO[suffix] = data
                        elif suffix == "imu_ok":
                            C.LAST_XGO["imu_ok"] = bool(data)
                        elif suffix == "fw":
                            fw = C._sanitize_fw(data)
                            if fw is not None:
                                C.XGO_FW = fw
                        elif isinstance(data, dict):
                            _update_xgo_from_dict(data)
                    continue

                if topic.startswith("xgo."):
                    suffix = topic[len("xgo.") :].lstrip(".")
                    data = _json_or_raw(payload)
                    C.LAST_XGO["ts"] = C.LAST_MSG_TS
                    if suffix == "pose":
                        if data not in (None, "", []):
                            C.LAST_XGO["pose"] = data
                    elif suffix == "pose_label":
                        if data not in (None, "", []):
                            C.LAST_XGO["pose_label"] = data
                    elif suffix in ("battery", "battery_pct"):
                        b = C._sanitize_batt(data) if data is not None else None
                        if b is not None:
                            C.LAST_XGO["battery"] = b
                    elif suffix in ("roll", "pitch", "yaw"):
                        try:
                            v = float(data) if data is not None else None
                            if v is not None:
                                if suffix == "yaw":
                                    v = C._norm_angle180(v)
                                prev = C.LAST_XGO.get(suffix)
                                if (v == 0.0) and (prev not in (None, 0.0)):
                                    pass
                                else:
                                    C.LAST_XGO[suffix] = v
                        except Exception:
                            C.LAST_XGO[suffix] = data
                    elif suffix == "imu_ok":
                        C.LAST_XGO["imu_ok"] = bool(data)
                    elif suffix == "fw":
                        fw = C._sanitize_fw(data)
                        if fw is not None:
                            C.XGO_FW = fw
                    elif isinstance(data, dict):
                        _update_xgo_from_dict(data)
                    continue

                if topic.startswith("motion.bridge.telemetry"):
                    try:
                        d = json.loads(payload) if payload else {}
                        _update_xgo_from_dict(d)
                    except Exception:
                        pass
                    continue

                if topic == "motion.bridge.battery_pct":
                    b = C._sanitize_batt(_json_or_raw(payload))
                    if b is not None:
                        C.LAST_XGO["ts"] = C.LAST_MSG_TS
                        C.LAST_XGO["battery"] = b
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

                if topic == "imu.data":
                    data = _json_or_raw(payload)
                    if isinstance(data, dict):
                        ts_val = data.get("ts") or C.LAST_MSG_TS
                        try:
                            C.LAST_XGO["ts"] = float(ts_val)
                        except Exception:
                            C.LAST_XGO["ts"] = C.LAST_MSG_TS
                        axes = {"roll": None, "pitch": None, "yaw": None}
                        for axis in ("roll", "pitch", "yaw"):
                            if data.get(axis) is None:
                                continue
                            try:
                                val = float(data.get(axis))
                                if axis == "yaw":
                                    val = C._norm_angle180(val)
                                C.LAST_XGO[axis] = val
                                axes[axis] = val
                            except Exception:
                                C.LAST_XGO[axis] = data.get(axis)
                                axes[axis] = data.get(axis)
                        src = data.get("yaw_src")
                        if src:
                            C.LAST_XGO["yaw_src"] = src
                        if any(v is not None for v in axes.values()):
                            C.LAST_XGO["pose"] = {"x": axes["roll"], "y": axes["pitch"], "z": axes["yaw"]}
                            pose_label = C._classify_pose(axes["roll"], axes["pitch"])
                            if pose_label:
                                C.LAST_XGO["pose_label"] = pose_label
                    continue

                if topic == "camera.heartbeat":
                    try:
                        data = json.loads(payload) if payload else {}
                        C.LAST_CAMERA["ts"] = C.LAST_MSG_TS
                        C.LAST_CAMERA["mode"] = data.get("mode")
                        C.LAST_CAMERA["fps"] = data.get("fps")
                        lcd = data.get("lcd") or {}
                        lcd_state = C.LAST_CAMERA["lcd"]
                        lcd_state.update(
                            {
                                "enabled_env": (not C.ENV_DISABLE_LCD),
                                "no_draw": C.ENV_NO_DRAW,
                                "rot": C.ENV_ROT,
                                "checked_at": C.LAST_MSG_TS,
                            }
                        )
                        for k in ("enabled_env", "no_draw", "rot", "active", "on", "presenting"):
                            if k in lcd:
                                lcd_state[k] = lcd[k]
                        if "active" in lcd:
                            lcd_state["presenting"] = bool(lcd.get("active"))
                            if lcd_state.get("on") is False and lcd_state["presenting"]:
                                lcd_state["on"] = True
                        lcd_state.setdefault("on", (not C.ENV_DISABLE_LCD) and (not C.ENV_NO_DRAW))
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
                    data = _json_or_raw(payload)
                    if isinstance(data, dict):
                        if "active" in data:
                            C.LAST_NAVIGATOR["active"] = bool(data.get("active"))
                        if data.get("state") is not None:
                            C.LAST_NAVIGATOR["state"] = data.get("state")
                        if data.get("strategy") is not None:
                            C.LAST_NAVIGATOR["strategy"] = data.get("strategy")
                        if "obstacle_present" in data:
                            C.LAST_NAVIGATOR["obstacle_present"] = bool(data.get("obstacle_present"))
                        C.LAST_NAVIGATOR["ts"] = float(data.get("ts") or C.LAST_MSG_TS)
                    continue

            except Exception:
                time.sleep(0.05)
    except Exception as e:
        print(f"[api] bus_sub_loop error: {e}", flush=True)


def xgo_ro_loop():
    """Legacy read-only entry uses the shared telemetry bus, never opens UART."""
    C.start_bus_sub()
