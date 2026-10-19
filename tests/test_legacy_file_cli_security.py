"""Exercise the actual legacy CLIs with fake display/network and hostile files."""

from __future__ import annotations

import errno
import importlib.util
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from common import secure_files

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cli():
    return load_script("dev_face-cli.py")


def test_stats_reports_valid_owned_artifacts(cli, tmp_path, capsys):
    base = str(tmp_path / "preview")
    (tmp_path / "preview.png").write_bytes(b"PNG")
    (tmp_path / "preview.meta.json").write_text(json.dumps({"mode": "png"}))
    cli.print_mock_stats(base)
    captured = capsys.readouterr()
    assert "preview.png: 3 B" in captured.out
    assert '"mode": "png"' in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "writable", "invalid", "oversize"])
def test_stats_never_discloses_hostile_metadata(cli, tmp_path, capsys, kind):
    target = tmp_path / "private"
    target.write_text('{"secret":"do-not-disclose"}')
    path = tmp_path / "preview.meta.json"
    if kind == "symlink":
        path.symlink_to(target)
    elif kind == "hardlink":
        os.link(target, path)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "writable":
        path.write_bytes(target.read_bytes())
        path.chmod(0o666)
    elif kind == "invalid":
        path.write_text("not-json")
    else:
        path.write_bytes(b" " * 65536 + target.read_bytes())
    cli.print_mock_stats(str(tmp_path / "preview"))
    captured = capsys.readouterr()
    assert "do-not-disclose" not in captured.out
    assert "Cannot inspect" in captured.err
    assert target.read_text() == '{"secret":"do-not-disclose"}'


def test_stats_rejects_linked_parent(cli, tmp_path, capsys):
    real = tmp_path / "real"
    real.mkdir()
    (real / "preview.meta.json").write_text('{"secret":"do-not-disclose"}')
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    cli.print_mock_stats(str(alias / "preview"))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Cannot inspect" in captured.err


def test_readonly_artifact_rejects_foreign_owner(tmp_path, monkeypatch):
    path = tmp_path / "preview"
    path.write_bytes(b"private")
    original = os.fstat

    def foreign(fd):
        info = original(fd)
        values = list(info)
        if stat.S_ISREG(info.st_mode):
            values[4] = os.geteuid() + 1
        return os.stat_result(values)

    monkeypatch.setattr(secure_files.os, "fstat", foreign)
    with pytest.raises(PermissionError, match="unsafe_runtime_artifact"):
        with secure_files.readonly_file(path):
            pytest.fail("foreign file must not be read")


def test_readonly_artifact_rejects_entry_swap_before_validation(tmp_path, monkeypatch):
    path = tmp_path / "preview"
    path.write_bytes(b"old")
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"private")
    original = os.stat

    def swap(name, *args, **kwargs):
        if name == path.name and kwargs.get("dir_fd") is not None:
            os.replace(replacement, path)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(secure_files.os, "stat", swap)
    with pytest.raises(PermissionError, match="unsafe_runtime_artifact"):
        with secure_files.readonly_file(path):
            pytest.fail("replaced entry must not be read")


def test_readonly_fdopen_failure_closes_descriptor(tmp_path, monkeypatch):
    path = tmp_path / "preview"
    path.write_bytes(b"data")
    opened = []

    def fail(fd, _mode):
        opened.append(fd)
        raise OSError("fdopen failed")

    monkeypatch.setattr(secure_files.os, "fdopen", fail)
    with pytest.raises(OSError, match="fdopen failed"):
        with secure_files.readonly_file(path):
            pytest.fail("fdopen must fail")
    with pytest.raises(OSError) as error:
        os.fstat(opened[0])
    assert error.value.errno == errno.EBADF


@pytest.mark.parametrize("backend", ["png", "lcd"])
def test_face_entrypoint_file_and_fallback_are_atomic(tmp_path, monkeypatch, backend):
    from apps.ui.face import __main__ as face

    victim = tmp_path / "private"
    victim.write_bytes(b"keep")
    output = tmp_path / "face.png"
    output.symlink_to(victim)
    controller = Mock()
    controller.frame_image.return_value = Image.new("RGB", (2, 2))
    controller.renderer.last_changed = True
    monkeypatch.setattr(face, "FaceController", Mock(return_value=controller))
    monkeypatch.setenv("FACE_BACKEND", backend)
    monkeypatch.setenv("FACE_USE_API", "0")
    monkeypatch.setenv("FACE_OUTFILE", str(output))
    monkeypatch.setattr(face.signal, "signal", Mock())
    framebuffer = Mock(return_value=False)
    monkeypatch.setattr(face, "write_framebuffer", framebuffer)

    def stop(_delay):
        raise KeyboardInterrupt

    monkeypatch.setattr(face.time, "sleep", stop)
    with pytest.raises(KeyboardInterrupt):
        face.main()
    assert victim.read_bytes() == b"keep"
    assert output.read_bytes().startswith(b"\x89PNG")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    if backend == "png":
        framebuffer.assert_not_called()
    else:
        framebuffer.assert_called_once()


@pytest.mark.parametrize("dry_run", [False, True])
def test_weather_fallback_and_dry_run_use_safe_png(tmp_path, monkeypatch, dry_run):
    weather = load_script("demo_weather-lcd.py")
    victim = tmp_path / "private"
    victim.write_bytes(b"keep")
    output = tmp_path / "weather.png"
    output.symlink_to(victim)
    args = SimpleNamespace(self_test=False, lat=1.0, lon=2.0, dry_run=dry_run, rotate=270, spi_hz=1)
    monkeypatch.setattr(weather, "parse_args", lambda: args)
    monkeypatch.setattr(weather, "fetch_weather", Mock(return_value={}))
    monkeypatch.setattr(weather, "render_card", Mock(return_value=Image.new("RGB", (2, 2))))
    lcd = Mock(side_effect=RuntimeError("display unavailable"))
    monkeypatch.setattr(weather, "push_to_lcd", lcd)
    original = secure_files.atomic_write
    outputs = []

    def local_write(path, writer):
        outputs.append(path)
        return original(output, writer)

    monkeypatch.setattr(weather, "atomic_write", local_write)
    assert weather.main() == (0 if dry_run else 5)
    assert outputs == (["weather.png"] if dry_run else ["/tmp/weather.png"])
    assert victim.read_bytes() == b"keep"
    assert output.read_bytes().startswith(b"\x89PNG")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    if dry_run:
        lcd.assert_not_called()
    else:
        lcd.assert_called_once()


def test_weather_offline_selftest_writes_atomic_png(tmp_path, monkeypatch):
    weather = load_script("demo_weather-lcd.py")
    victim = tmp_path / "private"
    victim.write_bytes(b"keep")
    output = tmp_path / "weather.png"
    output.symlink_to(victim)
    original = secure_files.atomic_write
    monkeypatch.setattr(weather, "atomic_write", lambda path, writer: original(output, writer))
    assert weather._self_tests() == 0
    assert victim.read_bytes() == b"keep"
    with Image.open(output) as image:
        assert image.size == (240, 320)
