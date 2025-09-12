#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, subprocess, platform, shutil, json
from flask import Response

def _cpu_pct_sample():
    try:
        with open("/proc/stat", "r") as f:
            line = f.readline()
        if not line.startswith("cpu "):
            return 0.0, 0.0
        parts = [float(x) for x in line.split()[1:]]
        idle = parts[3]; total = sum(parts)
        return idle, total
    except Exception:
        return 0.0, 0.0

_prev = {"idle": None, "total": None}
def cpu_percent():
    idle, total = _cpu_pct_sample()
    if not idle and not total: return 0.0
    if _prev["idle"] is None:
        _prev["idle"], _prev["total"] = idle, total
        time.sleep(0.03)
        idle2, total2 = _cpu_pct_sample()
        _prev["idle"], _prev["total"] = idle2, total2
        return 0.0
    diff_idle = idle - _prev["idle"]; diff_total = total - _prev["total"]
    _prev["idle"], _prev["total"] = idle, total
    if diff_total <= 0: return 0.0
    usage = (1.0 - (diff_idle / diff_total)) * 100.0
    return max(0.0, min(100.0, usage))

def load_avg():
    try: return os.getloadavg()
    except Exception: return (0.0, 0.0, 0.0)

def mem_info():
    total = avail = None
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"): total = float(line.split()[1]) * 1024.0
                elif line.startswith("MemAvailable:"): avail = float(line.split()[1]) * 1024.0
        if total and avail is not None:
            used = max(0.0, total - avail); pct = (used / total) * 100.0
            return {"total": total, "available": avail, "used": used, "pct": pct}
    except Exception:
        pass
    return {"total": 0.0, "available": 0.0, "used": 0.0, "pct": 0.0}

def disk_info(path="/"):
    try:
        du = shutil.disk_usage(path)
        used = du.used; pct = (used / du.total) * 100.0 if du.total else 0.0
        return {"total": du.total, "used": used, "free": du.free, "pct": pct}
    except Exception:
        return {"total": 0, "used": 0, "free": 0, "pct": 0.0}

def temp_c():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return float(f.read().strip()) / 1000.0
    except Exception:
        pass
    try:
        out = subprocess.check_output(["vcgencmd", "measure_temp"]).decode()
        v = out.strip().split("=")[-1].replace("'C","").replace("C","").replace("'","")
        return float(v)
    except Exception:
        return 0.0

def _os_info():
    pretty = None
    try:
        with open("/etc/os-release") as f:
            kv = {}
            for line in f:
                if "=" in line:
                    k,v = line.strip().split("=",1)
                    kv[k] = v.strip().strip('"')
            pretty = kv.get("PRETTY_NAME")
    except Exception:
        pass
    return {"pretty": pretty, "kernel": platform.release()}

_last_hist_t = 0.0
def get_sysinfo(HIST_CPU, HIST_MEM):
    global _last_hist_t
    ci = cpu_percent(); la1,la5,la15 = load_avg(); mi = mem_info(); di = disk_info("/"); tc = temp_c()
    now = time.time()
    if now - _last_hist_t >= 1.0:
        HIST_CPU.append(round(ci,1)); HIST_MEM.append(round(mi.get("pct",0.0),1))
        _last_hist_t = now
    si = {
        "ts": now,
        "cpu_pct": round(ci,1),
        "load": {"1": round(la1,2), "5": round(la5,2), "15": round(la15,2)},
        "mem": {"total": mi["total"], "available": mi["available"], "used": mi["used"], "pct": round(mi["pct"],1)},
        "disk": {"total": di["total"], "used": di["used"], "free": di["free"], "pct": round(di["pct"],1)},
        "temp_c": round(tc,1),
        "hist_cpu": list(HIST_CPU),
        "hist_mem": list(HIST_MEM),
        "os": _os_info(),
    }
    # bateria z LAST_XGO – uzupełnia compat.healthz/state, ale sysinfo może też ją podać:
    try:
        from . import compat
        if compat.LAST_XGO.get("battery") is not None:
            si["battery_pct"] = int(compat.LAST_XGO["battery"])
    except Exception:
        pass
    return si


def sysinfo():
    from . import compat
    si = get_sysinfo(compat.HIST_CPU, compat.HIST_MEM)
    out = {
        "cpu_pct": si["cpu_pct"],
        "load1": si["load"]["1"],
        "load5": si["load"]["5"],
        "load15": si["load"]["15"],
        "mem_total_mb": round(si["mem"]["total"] / 1048576, 1),
        "mem_used_mb": round(si["mem"]["used"] / 1048576, 1),
        "mem_pct": si["mem"]["pct"],
        "disk_total_gb": round(si["disk"]["total"] / 1073741824, 1),
        "disk_used_gb": round(si["disk"]["used"] / 1073741824, 1),
        "disk_pct": si["disk"]["pct"],
        "temp_c": si["temp_c"],
        "hist_cpu": si["hist_cpu"],
        "hist_mem": si["hist_mem"],
        "os_release": ((si["os"].get("pretty") or "—") + " · " + (si["os"].get("kernel") or "—")),
        "ts": si["ts"],
    }
    if "battery_pct" in si and si["battery_pct"] is not None:
        out["battery_pct"] = si["battery_pct"]
    return Response(json.dumps(out), mimetype="application/json")


def metrics():
    from . import compat
    si = get_sysinfo(compat.HIST_CPU, compat.HIST_MEM)
    now = time.time()
    last_msg_age = (now - compat.LAST_MSG_TS) if compat.LAST_MSG_TS else -1
    last_hb_age = (now - compat.LAST_HEARTBEAT_TS) if compat.LAST_HEARTBEAT_TS else -1
    cam_age = (now - compat.LAST_CAMERA["ts"]) if compat.LAST_CAMERA["ts"] else -1
    raw_age = -1
    if os.path.isfile(compat.RAW_PATH):
        try:
            raw_age = max(0.0, now - float(os.stat(compat.RAW_PATH).st_mtime))
        except Exception:
            raw_age = -1
    lines = []
    def m(name, val):
        lines.append(f"{name} {val}")
    m("rider_cpu_pct", si["cpu_pct"])
    m("rider_mem_pct", si["mem"]["pct"])
    m("rider_disk_pct", si["disk"]["pct"])
    m("rider_temp_c", si["temp_c"])
    if "battery_pct" in si and si["battery_pct"] is not None:
        m("rider_battery_pct", si["battery_pct"])
    m("rider_bus_last_msg_age_seconds", round(last_msg_age, 3))
    m("rider_bus_last_heartbeat_age_seconds", round(last_hb_age, 3))
    m("rider_camera_last_hb_age_seconds", round(cam_age, 3))
    m("rider_camera_raw_age_seconds", round(raw_age, 3))
    return Response("\n".join(lines) + "\n", mimetype="text/plain")
