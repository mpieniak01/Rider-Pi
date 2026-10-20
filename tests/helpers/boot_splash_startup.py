"""Exercise the real boot sequence with inert LCD/vendor commands and no API."""

import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_boot_splash_completes_before_api_is_available(tmp_path):
    robot = tmp_path / "robot"
    scripts = robot / "scripts"
    scripts.mkdir(parents=True)
    marker_dir = tmp_path / "run-rider"
    trace = tmp_path / "calls"
    # Only the hardcoded /run path is isolated. Execute the maintained script;
    # all external resource operations resolve to explicit inert fixtures.
    source = (ROOT / "scripts/sys_boot-prepare.sh").read_text()
    old_marker = 'MARKER_DIR="/run/rider"'
    assert source.count(old_marker) == 1
    (scripts / "sys_boot-prepare.sh").write_text(source.replace(old_marker, f'MARKER_DIR="{marker_dir}"'))
    splash = scripts / "sys_splash-info.sh"
    splash.write_text('#!/bin/sh\nprintf "splash rot=%s\\n" "$SPLASH_ROTATE" >> "$BOOT_TEST_TRACE"\n')
    splash.chmod(0o700)
    (scripts / "sys_lcd-power.py").write_text(
        'import os\nfrom pathlib import Path\n'
        'with Path(os.environ["BOOT_TEST_TRACE"]).open("a") as stream: stream.write("lcd-off\\n")\n'
    )
    (robot / "Makefile").write_text(
        'lcd-on:\n\t@echo rider_api_unavailable >&2\n\t@exit 1\n'
        'vendor-kill:\n\t@echo vendor-cleanup >> "$(BOOT_TEST_TRACE)"\n'
    )
    # Refuse unexpected display/process control instead of reaching host tools.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command in ("pkill", "systemctl", "sudo"):
        executable = bin_dir / command
        executable.write_text('#!/bin/sh\necho unexpected-process-control >> "$BOOT_TEST_TRACE"\nexit 99\n')
        executable.chmod(0o700)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "LANG": "C.UTF-8"}
    unit = (ROOT / "systemd/rider-boot-splash.service").read_text().splitlines()
    for line in unit:
        if line.startswith("Environment="):
            env.update(value.split("=", 1) for value in shlex.split(line.split("=", 1)[1]))
    env.update(ROBOT_ROOT=str(robot), BOOT_VENDOR_GRACE="0", BOOT_TEST_TRACE=str(trace))
    assert env["NO_KILL_DISPLAY"] == "1"
    commands = [line.split("=", 1)[1] for line in unit if line.startswith(("ExecStartPre=", "ExecStart="))]
    assert commands
    for command in commands:
        args = [value.replace("/home/pi/robot", str(robot)) for value in shlex.split(command)]
        if args[0] == "/usr/bin/make":
            assert args[1:] == ["-C", str(robot), "lcd-on"]
        elif args == [str(scripts / "sys_boot-prepare.sh")]:
            args.insert(0, shutil.which("bash"))
        else:
            raise AssertionError(f"Unit command outside inert fixture scope: {args}")
        result = subprocess.run(args, env=env, text=True, capture_output=True, timeout=10)
        assert result.returncode == 0, result.stdout + result.stderr
    assert (marker_dir / "boot-prepared").is_file()
    assert trace.read_text().splitlines() == ["vendor-cleanup", "splash rot=270", "lcd-off"]
    # The script's own marker makes a repeated request inert, independently
    # of systemd's ConditionPathExists; it must not touch an existing LCD owner.
    result = subprocess.run(
        [shutil.which("bash"), str(scripts / "sys_boot-prepare.sh")],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert trace.read_text().splitlines() == ["vendor-cleanup", "splash rot=270", "lcd-off"]


def main():
    """Run only temporary-root fixtures; never import hardware or contact a robot."""
    with tempfile.TemporaryDirectory(prefix="rider-boot-offline-") as folder:
        test_boot_splash_completes_before_api_is_available(Path(folder))
    print("PASS: boot without API; vendor/splash/OFF order; marker is idempotent")


if __name__ == "__main__":
    main()
