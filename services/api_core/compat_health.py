"""Health and telemetry handlers using the live compatibility namespace.

The caller supplies C so mutable state and monkeypatches remain authoritative.
No hardware, subscribers or application instance are created by this module.
"""

from __future__ import annotations

from common.observations import source_time


def lcd_snapshot(C, *, now):
    """Reported LCD I/O and preview settings have different owners and clocks."""
    state = C.LAST_CAMERA.get("lcd", {})
    at = source_time(state.get("observed_at"))
    source = state.get("source")
    reported = isinstance(source, str) and bool(source.strip()) and at is not None
    power_at = source_time(state.get("power_observed_at"))
    known = (
        reported
        and isinstance(state.get("on"), bool)
        and state.get("power_known") is True
        and state.get("confirmation") == "control_write_accepted"
        and state.get("power_source") == source
        and power_at == at
    )
    return {
        "on": state["on"] if known else None,
        "power_known": bool(known),
        "source": source if reported else None,
        "observed_at": at if reported else None,
        "observed_age_s": round(now - at, 3) if reported else None,
        "power_source": state.get("power_source") if known else None,
        "power_observed_at": power_at if known else None,
        "confirmation": state.get("confirmation") if reported else None,
        "physical_validity": state.get("physical_validity") if reported else None,
        "reason": state.get("reason") if reported else None,
        "rot": state.get("rot") if reported else None,
        "no_draw": state.get("no_draw") if reported else None,
        "presenting": state.get("presenting"),
        "frame": state.get("frame") if reported else None,
        "frame_source": state.get("frame_source") if reported else None,
        "frame_observed_at": state.get("frame_observed_at") if reported else None,
        "battery": state.get("battery") if reported else None,
        "configured_on": (not C.ENV_DISABLE_LCD) and (not C.ENV_NO_DRAW),
        "configured_no_draw": C.ENV_NO_DRAW,
        "configured_rot": C.ENV_ROT,
        "configured_rot_source": "api_env.PREVIEW_ROT",
        "preview_config": state.get("preview_config"),
        **{
            key: state.get(key)
            for key in (
                "holders",
                "checked_at",
                "auto_off_ts",
                "ownership_state",
                "ownership_error",
                "idle_for_s",
                "idle_release_requires_operator",
            )
        },
    }


def healthz(C):
    now = C.time.time()
    last_msg_age = (now - C.LAST_MSG_TS) if C.LAST_MSG_TS else None
    last_hb_age = (now - C.LAST_HEARTBEAT_TS) if C.LAST_HEARTBEAT_TS else None

    cam_ts = C.LAST_CAMERA.get("ts")
    cam_age = (now - cam_ts) if cam_ts else None
    camera_on = cam_age is not None and 0 <= cam_age <= 5.0

    from .devices import xgo_snapshot

    xgo = xgo_snapshot(now=now)
    channels = xgo["observation"]["sensor_quality"]["sensors"]
    times = [row["observed_at"] for row in channels.values() if row["observed_at"] is not None]
    xgo_age = min(now - at for at in times) if times else None
    # Unknown is never OFF. An available channel does not prove all IMU ready.
    xgo_on = True if any(row["ready"] for row in channels.values()) else None

    devices = {
        "camera": {
            "on": camera_on,
            "age_s": (round(cam_age, 3) if cam_age is not None else None),
            "mode": C.LAST_CAMERA.get("mode"),
            "fps": C.LAST_CAMERA.get("fps"),
        },
        "lcd": lcd_snapshot(C, now=now),
        "xgo": {**xgo, "on": xgo_on, "age_s": round(xgo_age, 3) if xgo_age is not None else None},
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
    from .bus_health import snapshot

    payload = snapshot(C)
    return C.Response(C.json.dumps(payload), mimetype="application/json")


def readyz(C):
    from .bus_health import snapshot

    payload = snapshot(C)
    return C.Response(C.json.dumps(payload), mimetype="application/json", status=200 if payload["ready"] else 503)


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


def events(C):
    from .event_stream import EventCursor

    @C.stream_with_context
    def gen():
        cursor = EventCursor()
        idle = 0
        while True:
            try:
                C.time.sleep(1.0)
                rows = cursor.drain(list(C.EVENTS))
                for ev in rows:
                    yield f'data: {C.json.dumps(ev)}\n\n'
                idle = 0 if rows else idle + 1
                if idle >= 10:
                    yield ': keepalive\n\n'
                    idle = 0
            except GeneratorExit:
                break
            except Exception:
                C.time.sleep(0.5)

    response = C.Response(gen(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Accel-Buffering'] = 'no'
    return response
