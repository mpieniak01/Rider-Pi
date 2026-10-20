"""Boot/service LCD handover without kernel guard bypass or vendor initialization."""

import ast
import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from drivers.lcd import lease

ROOT = Path(__file__).resolve().parents[1]


def test_existing_lcd_lock_opens_without_create_under_sticky_directory_policy(tmp_path, monkeypatch):
    path = tmp_path / "lcd.lock"
    path.write_bytes(b"stable-lock")
    path.chmod(0o644)
    before = path.stat()
    monkeypatch.setenv("RIDER_LCD_OWNER_LOCK", str(path))
    original = os.open

    def protected_open(name, flags, mode=0o777, *, dir_fd=None):
        if name == path.name and flags & os.O_CREAT:
            raise PermissionError("fs.protected_regular: existing lock belongs to another allowed UID")
        return original(name, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(lease.os, "open", protected_open)
    with lease.LCDLease():
        assert path.read_bytes() == b"stable-lock"
    after = path.stat()
    assert (after.st_ino, after.st_uid, after.st_mode) == (before.st_ino, before.st_uid, before.st_mode)


def test_lcd_lock_concurrent_creator_is_reopened_and_validated(tmp_path, monkeypatch):
    path = tmp_path / "lcd.lock"
    monkeypatch.setenv("RIDER_LCD_OWNER_LOCK", str(path))
    original = os.open
    attempts = []

    def racing_open(name, flags, mode=0o777, *, dir_fd=None):
        if name == path.name:
            attempts.append(flags)
            if len(attempts) == 1 and not flags & os.O_CREAT:
                path.write_bytes(b"concurrent-creator")
                path.chmod(0o644)
                raise FileNotFoundError(name)
        return original(name, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(lease.os, "open", racing_open)
    with lease.LCDLease():
        assert path.read_bytes() == b"concurrent-creator"
    assert len(attempts) == 3
    assert attempts[1] & os.O_CREAT and attempts[1] & os.O_EXCL
    assert not attempts[0] & os.O_CREAT and not attempts[2] & os.O_CREAT


def test_lcd_lock_racing_symlink_never_opens_or_changes_target(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.write_bytes(b"preserve")
    path = tmp_path / "lcd.lock"
    monkeypatch.setenv("RIDER_LCD_OWNER_LOCK", str(path))
    original = os.open

    def racing_open(name, flags, mode=0o777, *, dir_fd=None):
        if name == path.name and flags & os.O_CREAT:
            path.symlink_to(target)
        return original(name, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(lease.os, "open", racing_open)
    with pytest.raises(OSError):
        lease.LCDLease()
    assert target.read_bytes() == b"preserve"
    assert path.is_symlink()


@pytest.mark.parametrize("backend_exists", [False, True])
def test_splash_availability_probe_never_imports_vendor_package(tmp_path, monkeypatch, backend_exists):
    package = tmp_path / "xgoscreen"
    package.mkdir()
    (package / "__init__.py").write_text('raise AssertionError("vendor package initialized before LCD lease")\n')
    if backend_exists:
        (package / "LCD_2inch.py").write_text('raise AssertionError("SPI opened before LCD lease")\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ["xgoscreen", "xgoscreen.LCD_2inch"]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    source = ast.parse((ROOT / "scripts/sys_splash-info.py").read_text())
    function = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "have_xgo")
    namespace = {"importlib": importlib}
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / "scripts/sys_splash-info.py"), "exec"),
        namespace,
    )
    try:
        assert namespace["have_xgo"]() is backend_exists
        assert "xgoscreen" not in sys.modules
        assert "xgoscreen.LCD_2inch" not in sys.modules
    finally:
        for name in ["xgoscreen", "xgoscreen.LCD_2inch"]:
            sys.modules.pop(name, None)
