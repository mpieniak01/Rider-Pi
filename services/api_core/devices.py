#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import time

from common.observations import legacy_xgo, normalize_xgo_observation, observation, refresh_observation, source_time

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
    return source_time(value)


def _update_xgo_from_dict(data, topic="devices.xgo"):
    row = normalize_xgo_observation(topic, data)
    if row is None:
        return False
    previous = C.LAST_XGO.get("observation")
    previous = previous if isinstance(previous, dict) else {}
    rows = dict(previous.get("sensor_quality", {}).get("sensors", {}))
    instance_changed = (
        previous.get("instance_id") and row.get("instance_id") and previous["instance_id"] != row["instance_id"]
    )
    if instance_changed:
        rows.clear()
    for name, sample in row["sensor_quality"]["sensors"].items():
        old = rows.get(name, {})
        if (
            source_time(old.get("observed_at")) is not None
            and source_time(sample.get("observed_at")) is not None
            and sample["observed_at"] < old["observed_at"]
        ):
            sample = {**sample, "ready": False, "error": "measurement_out_of_order"}
        rows[name] = sample
    combined = observation(
        rows,
        source=row["source"],
        firmware=row.get("fw") if "fw" in data else previous.get("fw"),
        instance_id=row.get("instance_id") or previous.get("instance_id"),
        uart_owner=row.get("uart_owner") or previous.get("uart_owner"),
        generated_at=row.get("generated_at"),
        offline=row["offline"],
        error=row["error"],
    )
    legacy = legacy_xgo(combined)
    C.LAST_XGO.update(legacy)
    C.LAST_XGO["battery"] = legacy["battery_pct"]  # cache legacy percent, never magnitude inference
    C.LAST_XGO["pose_label"] = None  # raw SDK axes are not evidence of posture
    if row.get("fw") is not None:
        C.XGO_FW = C._sanitize_fw(row["fw"])
    if "yaw_src" in data:
        C.LAST_XGO["yaw_src"] = data["yaw_src"]
    return True


def observe_xgo(topic: str, data: object) -> bool:
    """Project source measurements without receipt timestamps or unit guesses."""
    if normalize_xgo_observation(topic, data) is None:
        return False
    normalized = data if isinstance(data, dict) else {}
    if not isinstance(data, dict):
        # The named scalar topic adapter also preserves unknown source time.
        prefix = next(
            (
                p
                for p in ("devices.xgo", "xgo", "motion.bridge.telemetry", "motion.bridge")
                if topic.startswith(p + ".")
            ),
            None,
        )
        if prefix:
            normalized = {topic[len(prefix) + 1 :]: data}
    return _update_xgo_from_dict(normalized, topic)


def xgo_snapshot(*, now=None):
    """Legacy HTTP projection plus its exact canonical observation.

    negotiated HTTP data replaces this object with `observation`; both come
    from the same cache and original per-channel times. No I/O occurs here.
    """
    cached = C.LAST_XGO.get("observation")
    if not isinstance(cached, dict):
        # Existing cache schema is HTTP percent, independently of value size.
        old = dict(C.LAST_XGO)
        old.update(battery=old.get("battery"), battery_unit="percent", fw=C.XGO_FW)
        if "yaw_raw" in old:
            old["yaw"] = old["yaw_raw"]
        cached = normalize_xgo_observation("xgo", old, now=now)
    current = refresh_observation(cached, now=now)
    return legacy_xgo(current)


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
        state["power_source"] = data.get("source") or "camera.heartbeat"
        state["power_observed_at"] = source_time(data.get("observed_at", data.get("ts")))
        for key in ("confirmation", "physical_validity", "reason"):
            if key in lcd:
                state[key] = lcd[key]


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
            "ui.lcd.state",
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
                if topic == "ui.lcd.state":
                    observe_lcd(_json_or_raw(payload))
                    continue
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
                        C.LAST_STATE["ts"] = _source_time(data.get("observed_at", data.get("ts")))
                        for key in ("source", "observed_at", "stale", "offline", "error", "data_ready"):
                            if key in data:
                                C.LAST_STATE[key] = data[key]
                    except Exception:
                        pass
                    continue

                if topic == "camera.heartbeat":
                    try:
                        data = json.loads(payload) if payload else {}
                        C.LAST_CAMERA["ts"] = _source_time(data.get("observed_at", data.get("ts")))
                        for key in ("observed_at", "source", "stale", "offline", "error", "capture_at", "frame_id"):
                            if key in data:
                                C.LAST_CAMERA[key] = data[key]
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

                # Command receipt is an intent, never observed actuator state.
                # /api/control/state reads actuators from the executor's ACK/state.
                if topic in {"cmd.balance", "cmd.height"}:
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
                    C.LAST_TRACKING_MODE["ts"] = (
                        _source_time(data.get("observed_at", data.get("ts"))) if isinstance(data, dict) else None
                    )
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
                        C.LAST_TRACKING_OFFSET["ts"] = _source_time(data.get("observed_at", data.get("ts")))
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
