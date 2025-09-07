#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import time, json
from typing import Any
from . import compat as C

def _json_or_raw(payload: str):
    try:
        return json.loads(payload) if payload not in (None, "") else None
    except Exception:
        s = (payload or "").strip()
        if s == "": return None
        try:
            if "." in s or "e" in s.lower(): return float(s)
            return int(s)
        except Exception:
            pass
        if "," in s and not s.startswith("{") and not s.startswith("["):
            parts = [p.strip() for p in s.split(",")]
            out = []
            for p in parts:
                try:
                    if "." in p or "e" in p.lower(): out.append(float(p))
                    else: out.append(int(p))
                except Exception:
                    out.append(p)
            return out
        return s

def _update_xgo_from_dict(d: dict):
    if not isinstance(d, dict): return
    ts = float(d.get("ts") or time.time())
    C.LAST_XGO["ts"] = ts

    if "imu_ok" in d: C.LAST_XGO["imu_ok"] = bool(d.get("imu_ok"))
    if "pose" in d and d.get("pose") is not None:
        C.LAST_XGO["pose"] = d.get("pose")

    bat = d.get("battery_pct", d.get("battery"))
    bat = C._sanitize_batt(bat) if bat is not None else None
    if bat is not None: C.LAST_XGO["battery"] = bat

    for k in ("roll","pitch","yaw"):
        if k in d and d.get(k) is not None:
            try:
                val = float(d.get(k))
                if k == "yaw": val = C._norm_angle180(val)
                prev = C.LAST_XGO.get(k)
                if (val == 0.0) and (prev not in (None, 0.0)):
                    pass
                else:
                    C.LAST_XGO[k] = val
            except Exception:
                C.LAST_XGO[k] = d.get(k)

    fw = C._sanitize_fw(d.get("fw"))
    if fw is not None:
        C.XGO_FW = fw

def _decode_frames(frames):
    if not frames: return "", ""
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
        for t in ("vision.", "camera.", "motion.bridge.", "motion.", "cmd.", "devices.", "xgo."):
            sub.setsockopt_string(zmq.SUBSCRIBE, t)
        try: sub.setsockopt(zmq.RCVTIMEO, 1000)
        except Exception: pass
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
                    suffix = topic[len("devices.xgo"):].lstrip(".")
                    data = _json_or_raw(payload)
                    if suffix == "" and isinstance(data, dict):
                        _update_xgo_from_dict(data)
                    else:
                        C.LAST_XGO["ts"] = C.LAST_MSG_TS
                        if suffix == "pose":
                            if data not in (None, "", []): C.LAST_XGO["pose"] = data
                        elif suffix in ("battery","battery_pct"):
                            b = C._sanitize_batt(data) if data is not None else None
                            if b is not None: C.LAST_XGO["battery"] = b
                        elif suffix in ("roll","pitch","yaw"):
                            try:
                                v = float(data) if data is not None else None
                                if v is not None:
                                    if suffix == "yaw": v = C._norm_angle180(v)
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
                            if fw is not None: C.XGO_FW = fw
                        elif isinstance(data, dict):
                            _update_xgo_from_dict(data)
                    continue

                if topic.startswith("xgo."):
                    suffix = topic[len("xgo."):].lstrip(".")
                    data = _json_or_raw(payload)
                    C.LAST_XGO["ts"] = C.LAST_MSG_TS
                    if suffix == "pose":
                        if data not in (None, "", []): C.LAST_XGO["pose"] = data
                    elif suffix in ("battery","battery_pct"):
                        b = C._sanitize_batt(data) if data is not None else None
                        if b is not None: C.LAST_XGO["battery"] = b
                    elif suffix in ("roll","pitch","yaw"):
                        try:
                            v = float(data) if data is not None else None
                            if v is not None:
                                if suffix == "yaw": v = C._norm_angle180(v)
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
                        if fw is not None: C.XGO_FW = fw
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
                        C.LAST_STATE["present"]    = bool(data.get("present", C.LAST_STATE["present"]))
                        C.LAST_STATE["confidence"] = float(data.get("confidence", C.LAST_STATE["confidence"]))
                        if "mode" in data: C.LAST_STATE["mode"] = data.get("mode")
                        C.LAST_STATE["ts"] = float(data.get("ts", C.LAST_MSG_TS))
                    except Exception:
                        pass
                    continue

                if topic == "camera.heartbeat":
                    try:
                        data = json.loads(payload) if payload else {}
                        C.LAST_CAMERA["ts"]   = C.LAST_MSG_TS
                        C.LAST_CAMERA["mode"] = data.get("mode")
                        C.LAST_CAMERA["fps"]  = data.get("fps")
                        lcd = data.get("lcd") or {}
                        C.LAST_CAMERA["lcd"].update({"enabled_env": (not C.ENV_DISABLE_LCD), "no_draw": C.ENV_NO_DRAW, "rot": C.ENV_ROT})
                        for k in ("enabled_env","no_draw","rot","active"):
                            if k in lcd: C.LAST_CAMERA["lcd"][k] = lcd[k]
                    except Exception:
                        pass
                    continue

            except Exception:
                time.sleep(0.05)
    except Exception as e:
        print(f"[api] bus_sub_loop error: {e}", flush=True)

def xgo_ro_loop():
    try:
        time.sleep(0.5)
        try:
            from tools.xgo_client_ro import XGOClientRO  # type: ignore
        except Exception as e:
            print("[api] xgo_ro_loop import error:", e, flush=True)
            return

        def _try_battery(cli):
            getters = [
                ("pct", getattr(cli, "read_battery_pct", None)),
                ("pct", getattr(cli, "get_battery_pct", None)),
                ("pct", getattr(cli, "battery_pct", None)),
                ("raw", getattr(cli, "read_battery", None)),
                ("raw", getattr(cli, "get_battery", None)),
                ("volt", getattr(cli, "read_voltage", None)),
                ("volt", getattr(cli, "get_voltage", None)),
                ("volt", getattr(cli, "voltage", None)),
            ]
            for kind, fn in getters:
                if not callable(fn): continue
                try: val = fn()
                except Exception: continue
                if val is None: continue
                if kind == "pct":
                    pct = C._sanitize_batt(val)
                elif kind == "volt":
                    pct = C._voltage_to_pct(val)
                else:
                    pct = C._sanitize_batt(val)
                if pct is not None:
                    return pct
            return None

        def _try_fw(cli):
            fns = [
                getattr(cli, "read_firmware", None),
                getattr(cli, "get_firmware", None),
                getattr(cli, "read_version", None),
                getattr(cli, "get_version", None),
            ]
            for fn in fns:
                if not callable(fn): continue
                try:
                    v = C._sanitize_fw(fn())
                    if v: return v
                except Exception:
                    pass
            return None

        cli = None
        while True:
            try:
                if cli is None:
                    cli = XGOClientRO(port="/dev/ttyAMA0")
                    print("[api] XGO RO connected: /dev/ttyAMA0", flush=True)

                if C.XGO_FW is None:
                    fw = _try_fw(cli)
                    if fw: C.XGO_FW = fw

                batt_pct = _try_battery(cli)

                roll = cli.read_roll()  if hasattr(cli, "read_roll")  else None
                pitch= cli.read_pitch() if hasattr(cli, "read_pitch") else None
                yaw_r= cli.read_yaw()   if hasattr(cli, "read_yaw")   else None
                yaw  = C._norm_angle180(yaw_r) if yaw_r is not None else None

                pose = C._classify_pose(roll, pitch)
                imu_ok = (roll is not None and pitch is not None and yaw is not None)

                upd = {"ts": time.time(), "imu_ok": bool(imu_ok)}
                if pose is not None: upd["pose"] = pose
                if batt_pct is not None: upd["battery"] = batt_pct
                if roll is not None:
                    if not (float(roll) == 0.0 and C.LAST_XGO.get("roll") not in (None, 0.0)):
                        upd["roll"] = float(roll)
                if pitch is not None:
                    if not (float(pitch) == 0.0 and C.LAST_XGO.get("pitch") not in (None, 0.0)):
                        upd["pitch"] = float(pitch)
                if yaw is not None:
                    if not (float(yaw) == 0.0 and C.LAST_XGO.get("yaw") not in (None, 0.0)):
                        upd["yaw"] = float(yaw)

                C.LAST_XGO.update(upd)
                time.sleep(1.0)
            except Exception:
                time.sleep(1.0); cli = None
    except Exception as e:
        print(f"[api] xgo_ro_loop error: {e}", flush=True)
