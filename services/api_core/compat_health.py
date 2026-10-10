"""Health and telemetry handlers using the live compatibility namespace.

The caller supplies C so mutable state and monkeypatches remain authoritative.
No hardware, subscribers or application instance are created by this module.
"""

from __future__ import annotations


def healthz(C):
    now = C.time.time()
    last_msg_age = (now - C.LAST_MSG_TS) if C.LAST_MSG_TS else None
    last_hb_age = (now - C.LAST_HEARTBEAT_TS) if C.LAST_HEARTBEAT_TS else None

    cam_ts = C.LAST_CAMERA.get("ts")
    cam_age = (now - cam_ts) if cam_ts else None
    camera_on = cam_age is not None and cam_age <= 5.0

    xgo_ts = C.LAST_XGO.get("ts")
    xgo_age = (now - xgo_ts) if xgo_ts else None
    xgo_on = xgo_age is not None and xgo_age <= 5.0

    inferred_pose = C.LAST_XGO.get("pose") or C._classify_pose(
        C.LAST_XGO.get("roll"),
        C.LAST_XGO.get("pitch"),
    )
    fw = C.XGO_FW if C.XGO_FW != "Null" else None

    yaw = C.LAST_XGO.get("yaw")
    try:
        yaw = round(float(yaw), 2) if yaw is not None else None
    except Exception:
        pass

    bat = C.LAST_XGO.get("battery")
    # Jednorazowe błyski 0% traktuj jako "brak odczytu".
    if isinstance(bat, (int, float)) and bat == 0 and xgo_on and (last_msg_age is not None and last_msg_age < 2.0):
        bat = None

    lcd_state = C.LAST_CAMERA.get("lcd", {})
    lcd_on = lcd_state.get("on")
    if lcd_on is None and lcd_state.get("power_known") is not False:
        lcd_on = (not C.ENV_DISABLE_LCD) and (not C.ENV_NO_DRAW)

    devices = {
        "camera": {
            "on": camera_on,
            "age_s": (round(cam_age, 3) if cam_age is not None else None),
            "mode": C.LAST_CAMERA.get("mode"),
            "fps": C.LAST_CAMERA.get("fps"),
        },
        "lcd": {
            "on": bool(lcd_on) if lcd_on is not None else None,
            "power_known": lcd_on is not None,
            "rot": lcd_state.get("rot", C.ENV_ROT),
            "no_draw": lcd_state.get("no_draw", C.ENV_NO_DRAW),
            "presenting": lcd_state.get("presenting"),
            "holders": lcd_state.get("holders"),
            "checked_at": lcd_state.get("checked_at"),
            "auto_off_ts": lcd_state.get("auto_off_ts"),
            "ownership_state": lcd_state.get("ownership_state"),
            "ownership_error": lcd_state.get("ownership_error"),
            "idle_for_s": lcd_state.get("idle_for_s"),
            "idle_release_requires_operator": lcd_state.get("idle_release_requires_operator"),
        },
        "xgo": {
            "on": xgo_on,
            "age_s": (round(xgo_age, 3) if xgo_age is not None else None),
            "imu_ok": C.LAST_XGO.get("imu_ok"),
            "pose": inferred_pose,
            "battery_pct": bat,
            "roll": C.LAST_XGO.get("roll"),
            "pitch": C.LAST_XGO.get("pitch"),
            "yaw": yaw,
            "fw": fw,
        },
    }

    status = "ok"
    if C.REQUIRE_VISION_HB:
        if (last_hb_age is None) or (last_hb_age > 10.0):
            status = "degraded"

    payload = {
        "status": status,
        "uptime_s": round(now - C.START_TS, 3),
        "bus": {
            "last_msg_age_s": (round(last_msg_age, 3) if last_msg_age is not None else None),
            "last_heartbeat_age_s": (round(last_hb_age, 3) if last_hb_age is not None else None),
        },
        "devices": devices,
        "state": {
            "present": bool(C.LAST_STATE.get("present", False)),
            "confidence": float(C.LAST_STATE.get("confidence", 0.0)),
            "mode": C.LAST_STATE.get("mode"),
            "age_s": (round(now - C.LAST_STATE["ts"], 3) if C.LAST_STATE.get("ts") else None),
        },
    }
    return C.Response(C.json.dumps(payload), mimetype="application/json")


def health_alias(C):
    return C.jsonify({"ok": True}), 200


def livez(C):
    # prosty „liveness”: proces żyje i podaje uptime
    up_s = C.time.time() - C.START_TS
    return C.Response(
        C.json.dumps({"alive": True, "uptime_s": round(up_s, 3)}),
        mimetype="application/json",
    )


def _git_info(C):
    """Spróbuj wyciągnąć commit/describe z gita (best-effort)."""
    try:
        desc = C.subprocess.check_output(
            ["git", "describe", "--always", "--dirty", "--tags"],
            cwd=C.BASE_DIR,
            text=True,
            timeout=1.0,
        ).strip()
    except Exception:
        desc = None
    try:
        rev = C.subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=C.BASE_DIR,
            text=True,
            timeout=1.0,
        ).strip()
    except Exception:
        rev = None
    return {"describe": desc, "commit": rev}


def api_version(C):
    """
    /api/version — lekka metryka wersji API/aplikacji.
    Zwraca: { name, api, ts, git: {describe, commit} }
    """
    info = C._git_info()
    payload = {
        "name": "rider-pi",
        "api": "v2",
        "ts": int(C.time.time()),
        "git": info,
    }
    return C.Response(C.json.dumps(payload), mimetype="application/json")


def api_bus_health(C):
    """
    /api/bus/health — zdrowie magistrali/telemetrii.
    """
    now = C.time.time()
    last_msg_age = (now - C.LAST_MSG_TS) if C.LAST_MSG_TS else None
    last_hb_age = (now - C.LAST_HEARTBEAT_TS) if C.LAST_HEARTBEAT_TS else None
    payload = {
        "zmq": {"available": bool(C._ZMQ_OK)},
        "ports": {"pub": C.BUS_PUB_PORT, "sub": C.BUS_SUB_PORT},
        "last_msg_age_s": (round(last_msg_age, 3) if last_msg_age is not None else None),
        "last_heartbeat_age_s": (round(last_hb_age, 3) if last_hb_age is not None else None),
        "ready_hint": (last_msg_age is None) or (last_msg_age < 30.0),
    }
    return C.Response(C.json.dumps(payload), mimetype="application/json")


def readyz(C):
    """
    /readyz — gotowość do obsługi żądań.
    - Jeśli pyzmq nieobecne → ready=True (nie blokujemy startu).
    - Jeśli BUS jest dostępny: gotowe, gdy ostatnia wiadomość nie starsza niż 30s.
    - Zawsze zwraca JSON (nawet gdy pojawi się wyjątek) — bez 500 z tracebackiem.
    """
    try:
        now = C.time.time()
        # LAST_MSG_TS bywa None lub liczbą; zabezpieczamy rzutowanie:
        last_msg_ts = C.LAST_MSG_TS
        last_msg_age = (now - float(last_msg_ts)) if last_msg_ts else None

        # Zabezpieczenie na wypadek, gdyby _ZMQ_OK nie był jeszcze w globals()
        zmq_ok = bool(getattr(C, "_ZMQ_OK", False))

        if not zmq_ok:
            ready = True
        else:
            # brak wiadomości jeszcze po starcie też traktujemy jako "ready"
            ready = (last_msg_age is None) or (last_msg_age < 30.0)

        payload = {
            "ready": bool(ready),
            "last_msg_age_s": (round(last_msg_age, 3) if last_msg_age is not None else None),
            "zmq_available": bool(zmq_ok),
        }
        return C.Response(C.json.dumps(payload), mimetype="application/json")
    except Exception as e:
        # awaryjnie: jasny JSON zamiast HTML 500
        err = {"ready": False, "error": str(e)}
        return C.Response(C.json.dumps(err), mimetype="application/json", status=500)


def api_status(C):
    """
    Minimalny payload kompatybilny z dawnym skryptem smoke:
    .system.cpu -> {count, percent}
    .devices.summary.flags -> {estop, motion_enable}
    """
    from .system_info import get_sysinfo

    si = get_sysinfo(C.HIST_CPU, C.HIST_MEM)
    flags = C._read_flags()
    payload = {
        "system": {
            "cpu": {
                "count": C.os.cpu_count() or 1,
                "percent": si["cpu_pct"],
            }
        },
        "devices": {"summary": {"flags": flags}},
    }
    return C.Response(C.json.dumps(payload), mimetype="application/json")


def api_metrics_alias(C):
    """
    Zwraca JSON zgodny ze starym API:
      { cpu: {count, percent}, mem: {percent, total, used},
        load: {"1m", "5m", "15m"}, uptime: {boot_time, uptime_s} }
    """
    from .system_info import get_sysinfo

    si = get_sysinfo(C.HIST_CPU, C.HIST_MEM)

    # CPU
    cpu = {
        "count": C.os.cpu_count() or 1,
        "percent": si["cpu_pct"],
    }

    # MEM
    mem = {
        "percent": si["mem"]["pct"],
        "total": si["mem"]["total"],
        "used": si["mem"]["used"],
    }

    # LOAD (klucze jak w starym)
    load = {
        "1m": si["load"]["1"],
        "5m": si["load"]["5"],
        "15m": si["load"]["15"],
    }

    # UPTIME
    try:
        with open("/proc/uptime") as f:
            up_s = float(f.read().split()[0])
    except Exception:
        up_s = max(0.0, C.time.time() - C.START_TS)
    boot_time = int(C.time.time() - up_s)

    uptime = {
        "boot_time": boot_time,
        "uptime_s": up_s,
    }

    payload = {"cpu": cpu, "mem": mem, "load": load, "uptime": uptime}
    return C.Response(C.json.dumps(payload), mimetype="application/json")


def api_devices(C):
    now = C.time.time()
    bus = {
        "broker": "unknown",
        "last_seen_ts": (now - ((now - C.LAST_MSG_TS) if C.LAST_MSG_TS else 0)),
    }
    lf_exists = C.os.path.isfile(C.RAW_PATH)
    lf_mtime = int(C.os.stat(C.RAW_PATH).st_mtime) if lf_exists else None
    vision = {
        "running": (C.LAST_CAMERA.get("ts") is not None),
        "last_frame": {
            "exists": bool(lf_exists),
            "mtime": lf_mtime,
            # DLA ZGODNOŚCI ZE STARYM API – zawsze raportuj "data/last_frame.jpg"
            "path": "data/last_frame.jpg",
        },
    }
    xgo = {
        "connected": bool(C.LAST_XGO.get("ts")),
        "last_telemetry_ts": C.LAST_XGO.get("ts"),
    }
    flags = C._read_flags()
    out = {"bus": bus, "vision": vision, "xgo": xgo, "flags": flags}
    return C.Response(C.json.dumps(out), mimetype="application/json")


def api_last_frame(C):
    exists = C.os.path.isfile(C.RAW_PATH)
    mtime = int(C.os.stat(C.RAW_PATH).st_mtime) if exists else None
    # dla zgodności ścieżkę raportujemy tak, jak w dawnym API (data/last_frame.jpg),
    # ale realny plik to snapshots/raw.jpg — aplikacje i tak korzystały z /camera/last.
    payload = {"exists": bool(exists), "mtime": mtime, "path": "data/last_frame.jpg"}
    return C.Response(C.json.dumps(payload), mimetype="application/json")
