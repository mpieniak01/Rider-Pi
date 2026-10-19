"""Isolation installed before pytest collection, independently of hardware flags."""

from __future__ import annotations

import builtins
import configparser
import importlib.abc
import io
import os
import re
import shlex
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


class IsolationError(RuntimeError):
    """An automated test attempted an unmocked hardware or production operation."""


class _NoRobotSDK(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"xgolib", "xgoedu", "RPi", "spidev", "gpiod"}:
            raise IsolationError("Robot SDK forbidden in pytest; inject an explicit mock")
        return None


def _fixture_git_root(cwd):
    configured = os.environ.get("RIDER_TEST_GIT_ROOT")
    if not configured or not cwd:
        return None
    root = Path(configured).resolve()
    current = Path(cwd).resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    if root == temporary or not root.is_relative_to(temporary) or not current.is_relative_to(root):
        return None
    return root


def _local_test_git(tokens, cwd):
    """Git transfer fixtures must name repositories inside an explicit temp root."""
    root = _fixture_git_root(cwd)
    if root is None:
        return False
    current = Path(cwd).resolve()
    verbs = {"push", "fetch", "pull", "ls-remote", "clone"}
    index = next((i for i, token in enumerate(tokens) if token in verbs), None)
    if index is None:
        return False
    arguments = [token for token in tokens[index + 1 :] if not token.startswith("-")]
    if not arguments:
        return False
    remote = arguments[0]
    config = configparser.ConfigParser(interpolation=None)
    config.read(current / ".git" / "config")
    section = 'remote "' + remote + '"'
    targets = [remote]
    if config.has_section(section):
        targets = [config.get(section, "url", fallback=""), config.get(section, "pushurl", fallback="")]
    for target in targets:
        if not target:
            continue
        path = Path(target[7:] if target.startswith("file://") else target)
        if "://" in str(path) or not path.is_absolute() or not path.resolve().is_relative_to(root):
            return False
    return bool(targets[0])


def _endpoint_allowed(endpoint: str, sandbox: Path) -> bool:
    if endpoint.startswith("inproc://"):
        return True
    if endpoint.startswith(f"ipc://{sandbox}/"):
        return True
    if endpoint.startswith(("tcp://127.0.0.1:", "tcp://localhost:", "tcp://[::1]:")):
        port = endpoint.rsplit(":", 1)[1]
        return port == "*" or port.isdigit() and int(port) >= 32768
    return False


def _check_device(path):
    if isinstance(path, (str, bytes, os.PathLike)):
        value = os.fsdecode(path)
        if value.startswith(("/dev/tty", "/dev/serial", "/dev/spidev", "/dev/gpiochip")):
            raise IsolationError("Real hardware device forbidden in pytest.")


def _check_address(sock, address, *, binding=False):
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        host, port = address[:2]
        allowed_port = int(port) >= 32768 or binding and int(port) == 0
        if host not in {"127.0.0.1", "localhost", "::1"} or not allowed_port:
            raise IsolationError(f"Unmocked production/network connection forbidden: {host}:{port}")


def _configure_environment(sandbox):
    os.environ.update(
        RIDER_TEST_ISOLATED="1",
        RIDER_PI_CI="1",
        RIDER_PI_MOCK_HW="1",
        FACE_STUDIO_LIBRARY=str(sandbox / "face-library.json"),
        FACE_RUNTIME_SETTINGS=str(sandbox / "face-runtime.json"),
        MOTION_ENABLE="0",
        MOTION_STATE_PATH=str(sandbox / "motion-status.json"),
        MOTION_FLAGS_DIR=str(sandbox / "flags"),
        FEATURE_STATE_PATH=str(sandbox / "feature_state.json"),
        PROVIDER_STATE_FILE=str(sandbox / "providers-state.json"),
        PROVIDER_WATCHDOG_DISABLED="1",
        ESTOP_GPIO="-1",
        ESTOP="0",
        BUS_XSUB="inproc://rider-pytest-publish",
        BUS_XPUB="inproc://rider-pytest-subscribe",
        BUS_PUB_ADDR="inproc://rider-pytest-publish",
        BUS_SUB_ADDR="inproc://rider-pytest-subscribe",
        BUS_PUB="inproc://rider-pytest-publish",
        BUS_SUB="inproc://rider-pytest-subscribe",
        FACE_LCD_BACKEND="mock",
        FACE_SINK="file",
        SDL_VIDEODRIVER="dummy",
        SDL_AUDIODRIVER="dummy",
    )


def _install_sdk_guard():
    sys.meta_path.insert(0, _NoRobotSDK())
    if "xgolib" in sys.modules or "xgoedu" in sys.modules:
        raise IsolationError("Robot SDK was imported before test isolation.")


def _install_device_guards():
    for module, name in ((os, "open"), (builtins, "open"), (io, "open")):
        original = getattr(module, name)

        def guarded_open(path, *args, original=original, **kwargs):
            _check_device(path)
            return original(path, *args, **kwargs)

        setattr(module, name, guarded_open)


def _child_environment(sandbox):
    # Child Python installs the same guards before user code, including python -c.
    project = Path(__file__).resolve().parents[1]
    (sandbox / "sitecustomize.py").write_text("from common.test_sandbox import install\ninstall()\n", encoding="utf-8")
    isolation_env = dict(os.environ)
    isolation_env["PYTHONPATH"] = os.pathsep.join((str(sandbox), str(project), os.environ.get("PYTHONPATH", "")))
    os.environ["PYTHONPATH"] = isolation_env["PYTHONPATH"]

    return isolation_env


def _socket_address_guard(original, *, binding=False):
    def guarded(sock, address):
        _check_address(sock, address, binding=binding)
        return original(sock, address)

    return guarded


def _socket_sendto_guard(original):
    def guarded(sock, data, *args):
        _check_address(sock, args[-1])
        return original(sock, data, *args)

    return guarded


def _install_socket_guards():
    socket.socket.connect = _socket_address_guard(socket.socket.connect)
    socket.socket.connect_ex = _socket_address_guard(socket.socket.connect_ex)
    socket.socket.bind = _socket_address_guard(socket.socket.bind, binding=True)
    socket.socket.sendto = _socket_sendto_guard(socket.socket.sendto)


def _install_bus_guards(sandbox):
    try:
        import zmq

        for name in ("connect", "bind"):
            original = getattr(zmq.Socket, name)

            def guarded(sock, endpoint, original=original):
                if not _endpoint_allowed(str(endpoint), sandbox):
                    raise IsolationError(f"Unmocked robot BUS forbidden: {endpoint}")
                return original(sock, endpoint)

            setattr(zmq.Socket, name, guarded)
    except ImportError:
        pass


def _install_serial_guard():
    try:
        import serial

        def serial_forbidden(*args, **kwargs):
            raise IsolationError("Real serial port forbidden in pytest; inject a mock")

        serial.Serial = serial_forbidden
    except ImportError:
        pass


def _validate_child_executable(executable, python_child, kwargs):
    permitted = {
        "git",
        "systemctl",
        "systemd-analyze",
        "journalctl",
        "lsof",
        "fuser",
        "ls",
        "stat",
        "pgrep",
        "uname",
        "hostname",
        "uptime",
        "id",
        "bash",
        "sh",
        "dash",
        "ffmpeg",
        "ffprobe",
        "fc-list",
    }
    if not python_child and executable not in permitted:
        raise IsolationError("Unapproved child executable forbidden in pytest: " + executable)
    if kwargs.get("shell"):
        raise IsolationError("Shell execution forbidden in automated tests; mock the runner.")


def _validate_command_names(tokens, names):
    if any(name in {"ssh", "scp", "sftp", "rsync", "curl", "wget", "sudo", "make"} for name in names):
        raise IsolationError("Unmocked external or administrative command forbidden in pytest.")
    if names and names[0] in {"bash", "sh", "dash", "zsh"}:
        allowed_scripts = {"config-init.sh", "diag_systemd-smoke.sh"}
        if len(names) < 2 or names[1] not in allowed_scripts or "-c" in tokens or "-lc" in tokens:
            raise IsolationError("Unmocked shell program forbidden in pytest.")


def _inherit_python_environment(tokens, kwargs, isolation_env):
    if any(flag in tokens for flag in ("-I", "-E", "-S")):
        raise IsolationError("Child Python must preserve test bootstrap isolation.")
    child_env = dict(kwargs.get("env") or os.environ)
    for key, value in isolation_env.items():
        if key.startswith(("RIDER_", "BUS_", "MOTION_", "FACE_")) or key in {
            "PYTHONPATH",
            "FEATURE_STATE_PATH",
        }:
            child_env[key] = value
    kwargs["env"] = child_env


def _validate_git_operation(tokens, executable, cwd):
    if executable == "git" and any(token in {"push", "fetch", "pull", "ls-remote", "clone"} for token in tokens):
        if not _local_test_git(tokens, cwd):
            raise IsolationError("Remote Git operations forbidden outside isolated file-only fixtures.")
    if executable == "git":
        readonly = {
            "status",
            "diff",
            "log",
            "show",
            "rev-parse",
            "rev-list",
            "ls-files",
            "ls-tree",
            "cat-file",
            "describe",
            "check-ignore",
            "merge-base",
            "--version",
        }
        arguments = tokens[1:]
        verb = next((token for token in arguments if not token.startswith("-")), None)
        if verb not in readonly and "--version" not in arguments:
            _validate_git_mutation(arguments, verb, cwd)


def _validate_git_mutation(arguments, verb, cwd):
    if _fixture_git_root(cwd) is None:
        raise IsolationError("Git mutation forbidden outside an explicit temporary fixture root.")
    redirects = {"-C", "--git-dir", "--work-tree", "--global", "--system"}
    global_config = "-c" in arguments and arguments.index("-c") < arguments.index(verb)
    if global_config or any(token.split("=", 1)[0] in redirects for token in arguments):
        raise IsolationError("Git fixture cannot redirect or alter external configuration.")


def _validate_system_operation(tokens, names):
    if "systemctl" in names:
        readonly = {"show", "status", "is-active", "is-enabled", "list-units", "list-unit-files", "--version"}
        arguments = tokens[names.index("systemctl") + 1 :]
        verbs = [token for token in arguments if not token.startswith("-")]
        verb = verbs[0] if verbs else None
        if verb not in readonly and "--version" not in arguments:
            raise IsolationError("Unmocked systemd mutation forbidden in pytest")
    if any(name in {"fuser", "kill", "pkill", "killall"} for name in names) and (
        "fuser" not in names or "-k" in tokens
    ):
        raise IsolationError("Unmocked process/device mutation forbidden in pytest")


def _popen_guard(original_popen, isolation_env):
    def popen(args, *positional, **kwargs):
        tokens = shlex.split(args) if isinstance(args, str) else [str(part) for part in args]
        names = [Path(token).name for token in tokens]
        executable = names[0] if names else ""
        python_child = re.fullmatch(r"python(?:3(?:\.\d+)?)?", executable) is not None
        _validate_child_executable(executable, python_child, kwargs)
        _validate_command_names(tokens, names)
        if python_child:
            _inherit_python_environment(tokens, kwargs, isolation_env)
        if executable in {"ffmpeg", "ffprobe"} and any("://" in token for token in tokens):
            raise IsolationError("Network media source forbidden in pytest.")
        _validate_git_operation(tokens, executable, kwargs.get("cwd"))
        _validate_system_operation(tokens, names)
        return original_popen(args, *positional, **kwargs)

    return popen


def _system_forbidden(*args, **kwargs):
    raise IsolationError("Unmocked shell execution forbidden in pytest.")


def install() -> None:
    if getattr(install, "installed", False):
        return
    install.installed = True
    install.sandbox = tempfile.TemporaryDirectory(prefix="rider-pytest-")
    sandbox = Path(install.sandbox.name)
    _configure_environment(sandbox)
    _install_sdk_guard()
    _install_device_guards()
    isolation_env = _child_environment(sandbox)
    _install_socket_guards()
    _install_bus_guards(sandbox)
    _install_serial_guard()
    subprocess.Popen = _popen_guard(subprocess.Popen, isolation_env)
    os.system = _system_forbidden
