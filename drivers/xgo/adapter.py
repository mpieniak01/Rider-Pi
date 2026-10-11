"""Sole-owner XGO adapter; public construction never opens physical hardware.

Only the executor supplies an in-process MotionGate and owner=True. The vendor
constructor calls reset/action255, so it is wrapped before any construction.
No second firmware autodetection constructor, timers, or direct client UART.
"""

from __future__ import annotations

import fcntl
import importlib
import os
import time
from collections.abc import Iterable
from pathlib import Path

from apps.safety.gate import MotionGate, finite_number
from common.motion_mapping import LINEAR_LEVELS, MAPPING_ID, TURN_LEVELS, linear_sdk_value, native_command_byte
from drivers.xgo.protocol import bound_serial, read_response
from drivers.xgo.sniffer import install as install_sniffer

XGO_PORT = os.getenv("XGO_PORT", "/dev/ttyAMA0")
XGO_VERSION = os.getenv("XGO_VERSION", "xgorider")
MOTION_ENABLE = False  # compatibility only; ENV never grants a lease


def uart_inventory(port: str, *, proc_root: str | Path | None = None) -> dict:
    """Inspect open descriptors without touching the device or sending signals.

    An unreadable process is UNKNOWN, never evidence that UART is free. The
    deployment procedure must stop old non-cooperating clients and provide a
    readable process inventory; this lock alone cannot exclude a legacy reader.
    """
    if proc_root is None:
        from common.uart_ownership import read_uart_owners

        return read_uart_owners(port, timeout_s=2.0)
    target = str(Path(port).resolve())
    owners = []
    unreadable = []
    try:
        processes = list(Path(proc_root).iterdir())
    except OSError:
        return {"known": False, "owners": [], "unreadable": ["proc"]}
    for process in processes:
        if not process.name.isdigit():
            continue
        try:
            descriptors = list((process / "fd").iterdir())
        except FileNotFoundError:
            continue  # process exited during this passive snapshot
        except OSError:
            unreadable.append(process.name)
            continue
        for descriptor in descriptors:
            try:
                destination = os.readlink(descriptor)
                if str(Path(destination).resolve()) == target:
                    owners.append(int(process.name))
                    break
            except FileNotFoundError:
                continue
            except OSError:
                unreadable.append(process.name)
                break
    return {"known": not unreadable, "owners": sorted(set(owners)), "unreadable": sorted(set(unreadable))}


def guarded_sdk_class(base, gate: MotionGate):
    """Guard the installed 1.4.2 SDK private write hook before its __init__.

    Reads are separate from __send. Unknown SDK layouts fail closed instead of
    constructing an unguarded object. During STOP only the explicit allowlist
    below is writable; no action/reset fallback can change the robot's posture.
    """
    send = getattr(base, "_XGO__send", None)
    unpack = getattr(base, "_XGO__unpack", None)
    read = getattr(base, "_XGO__read", None)
    if not callable(send) or not callable(unpack) or not callable(read):
        raise RuntimeError("unsupported_sdk_write_contract")

    orders = getattr(importlib.import_module(base.__module__), "XGOorder", None)

    class GuardedXGO(base):
        _initializing = True
        _stopping = False

        def __init__(self, *args, **kwargs):
            self._initializing = True
            self._expected_read = None
            try:
                super().__init__(*args, **kwargs)
                self._initializing = False
                serial = getattr(self, "ser", None)
                self.ser = serial = install_sniffer(serial)
                bound_serial(serial, 0.03)
                waiting = getattr(serial, "inWaiting", None)
                if callable(waiting):

                    def yielding_wait():
                        available = waiting()
                        if not available:
                            time.sleep(0.001)
                        return available

                    # SDK __unpack busy-spins on this method; yield only on the
                    # owned serial object instead of adding a polling daemon.
                    serial.inWaiting = yielding_wait
            except Exception:
                serial = getattr(self, "ser", None)
                if serial is not None:
                    serial.close()
                raise

        def reset(self):
            # Vendor constructor reset is a physical action, not initialization.
            if not self._initializing and gate.can_actuate():
                return super().reset()
            return None

        def _XGO__send(self, key, index=1, len=1):
            stopping_keys = {"VX", "VY", "VYAW", "MarkTime"}
            if self._initializing:
                return None
            if self._stopping:
                # Jawny STOP może wysłać tylko zera napędu; nie odpytuje bramy
                # ani trwałego zatrzasku. Błąd statusu nie może opóźnić STOP.
                if key not in stopping_keys:
                    raise PermissionError("unsupported_stop_write")
                if orders is not None and key in {"VX", "VY", "VYAW"}:
                    orders[key][1] = 128
                return send(self, key, index=index, len=len)
            if not gate.can_actuate():
                raise PermissionError("motion_gate_disarmed")
            native = getattr(self, "_command_native", None)
            if orders is not None and native is not None and native[0] == key:
                orders[key][1] = native_command_byte(native[1], native[2])
            return send(self, key, index=index, len=len)

        def _XGO__read(self, addr, read_len=1):
            if type(addr) is not int or not 0 <= addr <= 255 or type(read_len) is not int or not 0 < read_len <= 50:
                raise ValueError("unsupported_sensor_transaction")
            # A partial previous frame must not complete as the new sample.
            self.rx_FLAG = self.rx_COUNT = self.rx_ADDR = self.rx_LEN = 0
            self._expected_read = (addr, read_len, time.monotonic())
            try:
                bound_serial(self.ser, 0.25 if self._initializing else 0.03)
                return read(self, addr, read_len=read_len)
            except Exception:
                self._expected_read = None
                raise

        def _XGO__unpack(self, timeout=1):
            budget = 0.25 if self._initializing else 0.03
            expected, self._expected_read = self._expected_read, None
            if expected is None:
                raise TimeoutError("sensor_transaction_missing")
            addr, length, started = expected
            response = read_response(
                self.ser,
                address=addr,
                length=length,
                started_at=started,
                budget=min(timeout, budget),
                clock=time.monotonic,
            )
            self.rx_ADDR, self.rx_LEN, self.rx_TYPE = response["address"], response["length"], response["type"]
            self.rx_COUNT, self.rx_FLAG = length - 1, 0
            self.rx_data = bytearray(response["payload"])
            return True

    return GuardedXGO


class XgoAdapter:
    def __init__(
        self,
        port: str = XGO_PORT,
        version: str = XGO_VERSION,
        *,
        gate: MotionGate | None = None,
        owner: bool = False,
        sdk_factory=None,
        lock_path: str | Path | None = None,
        uart_probe=None,
    ):
        self._dog = None
        self._lock_fd = None
        self._gate = gate
        self._port, self._version = port, version
        self.error = "not_uart_owner"
        self.uart_inventory = None
        self._sdk_output = {"linear_step": None, "turn_step": None}
        if not owner or gate is None:
            return
        if os.getenv("RIDER_TEST_ISOLATED") == "1" and sdk_factory is None:
            self.error = "physical_sdk_blocked_in_tests"
            return
        try:
            if sdk_factory is None and port != "/dev/ttyAMA0":
                raise RuntimeError("sdk_1_4_2_ignores_custom_serial_port")
            path = Path(lock_path or f"/tmp/rider-motion-uart-{Path(port).name}.lock")
            self._lock_fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Injection exists only for an explicit fake SDK; production uses
            # the exact privileged read-only inventory, never an ENV free flag.
            probe = uart_probe if sdk_factory is not None and uart_probe is not None else uart_inventory
            self.uart_inventory = probe(port)
            if self.uart_inventory.get("owners"):
                raise RuntimeError("uart_owned_by_existing_process")
            if self.uart_inventory.get("known") is not True:
                raise RuntimeError("uart_inventory_unreadable")
            if sdk_factory is None:
                module = importlib.import_module("xgolib")
                if getattr(module, "__version__", None) != "1.4.2":
                    raise RuntimeError("unsupported_sdk_version")
                base = module.XGO
            else:
                base = sdk_factory
            sdk = guarded_sdk_class(base, gate)
            self._dog = sdk(port=port, version=version)
            self.error = None
            if not self.stop():
                raise RuntimeError("sdk_stop_unavailable")
        except Exception as exc:
            self.error = f"uart_initialization_failed:{type(exc).__name__}:{exc}"
            self.close()

    def ok(self) -> bool:
        return self._dog is not None and self.error is None

    def available_methods(self) -> list[str]:
        return sorted(m for m in dir(self._dog) if not m.startswith("_")) if self.ok() else []

    def _allowed(self) -> bool:
        return bool(self.ok() and self._gate is not None and self._gate.can_actuate())

    def _call(self, name: str, *args) -> bool:
        # A transport fault is latched for this owner. STOP remains retryable.
        if self.error is not None and name != "stop":
            return False
        fn = getattr(self._dog, name, None)
        if not callable(fn):
            return False
        native = None
        if args and name in {"rider_move_x", "move_x"}:
            native = ("VX", args[0], 1.5)
        elif args and name in {"turnleft", "turnright"}:
            native = ("VYAW", abs(args[0]) * (1 if name == "turnleft" else -1), 360.0)
        self._dog._command_native = native
        try:
            result = fn(*args)
            if result is False:
                self.error = f"sdk_call_unconfirmed:{name}"
                return False
            return True
        except Exception as exc:
            self.error = f"sdk_call_failed:{name}:{type(exc).__name__}"
            return False
        finally:
            self._dog._command_native = None

    def stop(self) -> bool:
        if self._dog is None:
            return False
        self._dog._stopping = True
        try:
            stopped = self._call("stop")
            if not stopped and self.error is None:
                self.error = "sdk_stop_unconfirmed"
            if stopped:
                self._sdk_output = {"linear_step": 0, "turn_step": 0}
            return stopped
        finally:
            self._dog._stopping = False

    def close(self) -> None:
        if self._dog is not None:
            try:
                self.stop()
                serial = getattr(self._dog, "ser", None)
                if serial is not None:
                    try:
                        serial.close()
                    except Exception as exc:
                        self.error = self.error or f"sdk_close_failed:{type(exc).__name__}"
            finally:
                self._dog = None
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    def _read(self, names: tuple[str, ...]):
        if not self.ok():
            return None
        for name in names:
            fn = getattr(self._dog, name, None)
            if callable(fn):
                try:
                    return fn()
                except OSError as exc:
                    self.error = f"sdk_read_failed:{name}:{type(exc).__name__}"
                    return None
                except Exception:
                    return None
        return None

    def battery(self) -> float | None:
        value = self._read(("rider_read_battery", "read_battery"))
        try:
            value = finite_number(value, "battery")
        except ValueError:
            return None
        # SDK 1.4.2 returns a percentage byte, including 0% and 1%.
        if not 0 <= value <= 100 or int(value) != value:
            return None
        return value / 100.0

    def imu(self) -> dict | None:
        values = {axis: self._read((f"rider_read_{axis}", f"read_{axis}")) for axis in ("roll", "pitch", "yaw")}
        try:
            return {key: finite_number(value, key) for key, value in values.items()}
        except ValueError:
            return None

    def read_axis(self, axis: str) -> float | None:
        if axis not in {"roll", "pitch", "yaw"}:
            return None
        value = self._read((f"rider_read_{axis}", f"read_{axis}"))
        try:
            return finite_number(value, axis)
        except ValueError:
            return None

    def firmware(self) -> str | None:
        value = self._read(("rider_read_firmware", "read_firmware"))
        return value.strip() if isinstance(value, str) and value.strip() else None

    read_firmware = firmware
    version = firmware

    def led(self, idx: int, rgb: Iterable[int]) -> bool:
        if not self._allowed():
            return False
        return self._call("rider_led", int(idx), list(rgb)[:3])

    def set_stabilization(self, on: bool) -> bool:
        return self.enable_balance(on)

    def enable_balance(self, on: bool) -> bool:
        if not self._allowed() or not isinstance(on, bool):
            return False
        if not self.capabilities()["balance"]["stop_verified"]:
            self.error = "balance_manual_characterization_required"
            return False
        return self._call("rider_balance_roll", int(on)) or self._call("imu", int(on))

    def set_height(self, h: int) -> bool:
        if not self._allowed() or isinstance(h, bool) or not isinstance(h, int) or not 75 <= h <= 115:
            return False
        if not self.capabilities()["height"]["stop_verified"]:
            self.error = "height_manual_characterization_required"
            return False
        return self._call("rider_height", h)

    def drive(self, dir: str, speed: float, dur: float | None = None, *, block: bool = False) -> bool:
        if not self._allowed() or dir not in {"forward", "backward"}:
            return False
        value = finite_number(speed, "speed")
        if not 0 <= value <= 1:
            return False
        step = round(value * LINEAR_LEVELS)
        step *= 1 if dir == "forward" else -1
        # Never invoke vendor runtime sleeps: executor owns the duration deadline.
        sdk_value = linear_sdk_value(step)
        done = self._call("rider_move_x", sdk_value, 0) or self._call("move_x", sdk_value, 0)
        if done:
            self._sdk_output["linear_step"] = step
        if block and dur is not None:
            self._bounded_wait(dur)
        return done

    def spin(
        self,
        dir: str,
        speed: float,
        dur: float | None = None,
        deg: float | None = None,
        *,
        block: bool = False,
    ) -> bool:
        if not self._allowed() or dir not in {"left", "right"} or deg is not None:
            return False
        value = finite_number(speed, "speed")
        if not 0 <= value <= 1:
            return False
        step = round(value * TURN_LEVELS)
        name = "turnleft" if dir == "left" else "turnright"
        done = self._call(name, step)
        if done:
            self._sdk_output["turn_step"] = step if dir == "left" else -step
        if block and dur is not None:
            self._bounded_wait(dur)
        return done

    def _bounded_wait(self, duration: float) -> None:
        deadline = time.monotonic() + min(0.25, max(0.0, finite_number(duration, "duration")))
        while self._allowed() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.stop()

    def action(self, name: str) -> bool:
        if not self._allowed() or name not in {"default", "sway", "vertical", "lift_rotate", "circular"}:
            return False
        if not self.capabilities()["action"]["stop_verified"]:
            self.error = "action_manual_characterization_required"
            return False
        action_id = {"default": 255, "sway": 1, "vertical": 2, "lift_rotate": 5, "circular": 6}[name]
        return self._call("rider_action", action_id, False) or self._call("action", action_id, False)

    def capabilities(self) -> dict:
        # Source proves that stop writes zero velocity. Physical behavior has
        # not been measured. Height/balance/actions have no cancellation proof.
        result = {}
        for name in ("move", "turn", "balance", "height", "action"):
            stop_verified = name in {"move", "turn"}
            result[name] = {
                "available": bool(self.ok() and stop_verified),
                "stop_verified": stop_verified,
                "verification": "sdk_source" if stop_verified else "manual_characterization_required",
                "physical_completion": "unverified",
            }
        return result

    def output_status(self) -> dict:
        """Accepted SDK command units, never encoder/velocity measurements."""
        linear = self._sdk_output["linear_step"]
        return {
            **self._sdk_output,
            "units": "command_levels",
            "mapping_id": MAPPING_ID,
            "linear_sdk_value": linear_sdk_value(linear) if linear is not None else None,
            "turn_sdk_value": self._sdk_output["turn_step"],
            "physical_completion": "unverified",
        }
