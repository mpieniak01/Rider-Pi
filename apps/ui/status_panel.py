"""LCD status lifecycle. No UART, SDK, service starts or device I/O on import.

The renderer shows startup/task changes briefly and yields to other LCD users.
Its periodic telemetry reads are never activity and cannot keep the light on.
Every power action requires a known current ownership inventory.
"""

from __future__ import annotations

import math
import os
import time

from common.observations import finite, observation, refresh_observation, source_time


def battery_observation(status, *, now=None):
    now = time.time() if now is None else now
    status = status if isinstance(status, dict) else {}
    quality = status.get("sensor_quality")
    quality = quality if isinstance(quality, dict) else {}
    rows = quality.get("sensors", {})
    row = rows.get("battery") if isinstance(rows, dict) else None
    at = source_time(status.get("observed_at"))
    identity = status.get("instance_id")
    parent_error = status.get("error")
    if isinstance(parent_error, str) and parent_error.startswith("sensor_quality:"):
        parent_error = None
    if (
        not isinstance(row, dict)
        or type(status.get("contract_version")) is not int
        or status.get("contract_version") != 1
        or not isinstance(identity, str)
        or not identity
        or at is None
        or not finite(now)
        or not 0 <= now - at <= 3
        or status.get("stale") is True
        or status.get("offline") is True
        or status.get("simulated") is True
        or row.get("simulated") is True
        or parent_error
        or row.get("source") is not None
        and row.get("source") != "motion-executor"
        or row.get("instance_id") is not None
        and row.get("instance_id") != identity
    ):
        return {"value": None, "ready": False, "observed_at": None, "unit": "ratio"}
    canonical = observation({"battery": row}, source="motion-executor", instance_id=status.get("instance_id"))
    return refresh_observation(canonical, now=now)["sensor_quality"]["sensors"]["battery"]


def battery_text(row):
    if row.get("ready") is True and row.get("value") is not None:
        return f"Battery: {row['value'] * 100:.0f}%"
    return "Battery: — (brak świeżego odczytu)"


def task_fingerprint(state):
    state = state if isinstance(state, dict) else {}
    features = state.get("features")
    features = features if isinstance(features, list) else []
    requested = state.get("requested", state.get("active", []))
    requested = requested if isinstance(requested, list) else []
    return (
        tuple(sorted(str(name) for name in requested)),
        tuple(sorted((str(row.get("name")), str(row.get("state"))) for row in features if isinstance(row, dict))),
    )


def ownership_permits(snapshot, *, pid=None):
    """Descriptor inventory is not power evidence; errors never grant ownership."""
    pid = os.getpid() if pid is None else pid
    if not isinstance(snapshot, dict) or snapshot.get("error") or type(snapshot.get("free")) is not bool:
        return False
    if snapshot["free"]:
        return not snapshot.get("holders")
    holders = snapshot.get("holders")
    return (
        isinstance(holders, list)
        and bool(holders)
        and all(isinstance(row, dict) and row.get("pid") == pid for row in holders)
    )


class StatusPanelLifecycle:
    def __init__(self, *, sink_factory, owner_probe, power_off, report=None, clock=time.monotonic, idle_s=45.0):
        self.sink_factory, self.owner_probe, self.power_off = sink_factory, owner_probe, power_off
        self.report = report or (lambda **fields: None)
        if not math.isfinite(idle_s) or idle_s <= 0:
            raise ValueError("invalid_lcd_idle_policy")
        self.clock, self.idle_s = clock, idle_s
        self.started = self.last_activity = clock()
        self.fingerprint = None
        self.last_screen = None
        self.sink = None
        self.off_confirmed = False
        self.initial_battery_shown = False
        self.rotate = None

    def _release(self):
        if self.sink is not None:
            self.sink.close()  # owned descriptors only; never GPIO/power here
            self.sink = None

    def step(self, state, battery, title, lines, warn=False, *, frame=None):
        now = self.clock()
        key = task_fingerprint(state)
        if self.fingerprint is not None and key != self.fingerprint:
            self.last_activity = now
            self.off_confirmed = False
        self.fingerprint = key
        # One late first battery frame is useful after executor starts, but it
        # does not reset idle and cannot revive an already sleeping display.
        fresh_first = not self.initial_battery_shown and battery.get("ready") is True
        if fresh_first and now - self.started < self.idle_s:
            self.last_screen = None
        if self.off_confirmed and now - self.last_activity >= self.idle_s:
            # No ownership scan or GPIO command on ordinary idle polls.
            return "idle_off"
        snapshot = self.owner_probe()
        if not ownership_permits(snapshot):
            self._release()
            return "ownership_unknown_or_external"
        if now - self.last_activity >= self.idle_s:
            self._release()
            if not self.off_confirmed and ownership_permits(self.owner_probe()):
                self.off_confirmed = self.power_off() is True
                self.report(
                    on=False if self.off_confirmed else None,
                    reason="status_idle",
                    power_known=self.off_confirmed,
                    rot=self.rotate,
                )
            return "idle_off" if self.off_confirmed else "idle_off_unconfirmed"
        screen = (title, tuple(lines) + (battery_text(battery),), bool(warn), frame)
        if self.sink is None:
            self.sink = self.sink_factory()
            self.rotate = getattr(self.sink, "rotate", None)
            self.last_screen = None
        if screen != self.last_screen:
            if frame is None:
                self.sink.display(screen[0], list(screen[1]), warn=screen[2])
            else:
                self.sink.display(screen[0], list(screen[1]), warn=screen[2], frame=frame)
            self.last_screen = screen
            power_known = getattr(self.sink, "power_known", False) is True
            self.report(
                on=True if power_known else None,
                reason="status_frame",
                power_known=power_known,
                presenting=True,
                rot=self.rotate,
                frame=getattr(self.sink, "frame_observation", None),
                battery={key: battery.get(key) for key in ("value", "unit", "source", "observed_at", "ready")},
            )
        self.initial_battery_shown |= battery.get("ready") is True
        return "presenting"

    def close(self):
        # Shutdown only affects this renderer; another renderer is untouched.
        permitted = ownership_permits(self.owner_probe())
        self._release()
        if permitted and ownership_permits(self.owner_probe()):
            return self.power_off() is True
        return False
