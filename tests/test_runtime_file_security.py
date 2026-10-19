"""Filesystem security regressions; no robot, bus, recording or display I/O."""

from __future__ import annotations

import errno
import os
import stat
import wave
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from apps.safety.gate import MotionGate
from apps.voice.svc_file_capture import FileCaptureMixin
from common import pidlock, runtime_lock, secure_files
from drivers.xgo.adapter import XgoAdapter
from services.api_core.face_anim import FileSink


def test_face_snapshot_does_not_follow_old_temporary_or_final_link(tmp_path):
    victim = tmp_path / "private"
    victim.write_bytes(b"keep")
    temporary = tmp_path / "face_latest.tmp"
    temporary.symlink_to(victim)
    output = tmp_path / "face_latest.png"
    output.symlink_to(victim)
    FileSink(str(output)).present(Image.new("RGB", (16, 16)))
    assert victim.read_bytes() == b"keep"
    assert temporary.is_symlink()
    assert not output.is_symlink()
    assert output.read_bytes().startswith(b"\x89PNG")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_failed_snapshot_keeps_old_image_and_removes_only_its_temporary(tmp_path):
    output = tmp_path / "face.png"
    output.write_bytes(b"old")

    def fail(stream, _format):
        stream.write(b"partial")
        raise RuntimeError("encoder failed")

    sink = FileSink(output)
    with pytest.raises(RuntimeError, match="encoder failed"):
        sink.present(SimpleNamespace(save=fail))
    assert output.read_bytes() == b"old"
    assert not list(tmp_path.glob(".rider-write-*"))
    assert not sink._written


@pytest.mark.parametrize("parent_link", [False, True])
def test_snapshot_refuses_symlink_directory_components(tmp_path, parent_link):
    real = tmp_path / "real"
    real.mkdir()
    (real / "nested").mkdir()
    link = tmp_path / "alias"
    link.symlink_to(real, target_is_directory=True)
    output = link / "nested" / "face.png" if parent_link else link / "face.png"
    with pytest.raises(OSError):
        FileSink(output).present(Image.new("RGB", (16, 16)))
    assert not list(real.rglob("*.png"))


def test_snapshot_refuses_non_sticky_public_directory(tmp_path):
    directory = tmp_path / "public"
    directory.mkdir(mode=0o777)
    directory.chmod(0o777)
    with pytest.raises(PermissionError, match="unsafe_runtime_directory"):
        FileSink(directory / "face.png").present(Image.new("RGB", (16, 16)))
    assert not list(directory.iterdir())


def test_atomic_writer_collision_preserves_preexisting_temporary(tmp_path, monkeypatch):
    monkeypatch.setattr(secure_files.secrets, "token_hex", lambda _size: "collision")
    temporary = tmp_path / ".rider-write-collision.tmp"
    temporary.write_bytes(b"other writer")
    with pytest.raises(FileExistsError):
        secure_files.atomic_write(tmp_path / "face.png", lambda stream: stream.write(b"new"))
    assert temporary.read_bytes() == b"other writer"
    assert not (tmp_path / "face.png").exists()


def test_fdopen_failure_closes_file_descriptor_and_removes_temporary(tmp_path, monkeypatch):
    captured = []

    def fail(fd, _mode):
        captured.append(fd)
        raise OSError("fdopen failed")

    monkeypatch.setattr(secure_files.os, "fdopen", fail)
    with pytest.raises(OSError, match="fdopen failed"):
        secure_files.atomic_write(tmp_path / "face.png", lambda stream: stream.write(b"new"))
    with pytest.raises(OSError) as error:
        os.fstat(captured[0])
    assert error.value.errno == errno.EBADF
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_pid_lock_refuses_links_before_touching_target(tmp_path, monkeypatch, link_kind):
    target = tmp_path / "private"
    target.write_bytes(b"private-data")
    lock = tmp_path / "owner.lock"
    if link_kind == "symlink":
        lock.symlink_to(target)
    else:
        os.link(target, lock)
    registered = []
    monkeypatch.setattr(pidlock.atexit, "register", registered.append)
    with pytest.raises(SystemExit) as error:
        pidlock.single_instance(lock)
    assert error.value.code == 1
    assert target.read_bytes() == b"private-data"
    assert registered == []


def test_lock_rejects_fifo_without_blocking(tmp_path):
    lock = tmp_path / "owner.lock"
    os.mkfifo(lock)
    with pytest.raises(PermissionError, match="unsafe_runtime_lock"):
        runtime_lock.open_owned(lock)


def test_lock_rejects_foreign_owner_before_chmod_or_write(tmp_path, monkeypatch):
    lock = tmp_path / "owner.lock"
    lock.write_bytes(b"foreign")
    lock.chmod(0o644)
    original = os.fstat

    def foreign_file(fd):
        info = original(fd)
        if stat.S_ISREG(info.st_mode):
            return SimpleNamespace(
                st_mode=info.st_mode,
                st_uid=os.geteuid() + 1,
                st_nlink=info.st_nlink,
                st_dev=info.st_dev,
                st_ino=info.st_ino,
            )
        return info

    monkeypatch.setattr(runtime_lock.os, "fstat", foreign_file)
    with pytest.raises(PermissionError, match="unsafe_runtime_lock"):
        runtime_lock.open_owned(lock)
    assert lock.read_bytes() == b"foreign"
    assert stat.S_IMODE(lock.stat().st_mode) == 0o644


def test_pid_cleanup_preserves_inode_and_later_owner_reuses_it(tmp_path, monkeypatch):
    lock = tmp_path / "owner.lock"
    registered = []
    monkeypatch.setattr(pidlock.atexit, "register", registered.append)
    pidlock.single_instance(lock)
    inode = lock.stat().st_ino
    registered[0]()
    assert lock.exists()
    pidlock.single_instance(lock)
    try:
        assert lock.stat().st_ino == inode
        assert lock.read_text() == str(os.getpid())
        assert stat.S_IMODE(lock.stat().st_mode) == 0o600
    finally:
        registered[1]()


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_uart_lock_rejection_precedes_inventory_and_sdk(tmp_path, link_kind):
    target = tmp_path / "private"
    target.write_bytes(b"keep")
    lock = tmp_path / "uart.lock"
    if link_kind == "symlink":
        lock.symlink_to(target)
    else:
        os.link(target, lock)
    sdk = Mock(side_effect=AssertionError("SDK must not be constructed"))
    inventory = Mock(side_effect=AssertionError("inventory must not be queried"))
    adapter = XgoAdapter(
        owner=True, gate=MotionGate(blocked=lambda: False), sdk_factory=sdk, lock_path=lock, uart_probe=inventory
    )
    assert not adapter.ok()
    sdk.assert_not_called()
    inventory.assert_not_called()
    assert target.read_bytes() == b"keep"
    adapter.close()


def recording_service(directory):
    return SimpleNamespace(
        _recordings_dir=directory,
        _capture_cfg=SimpleNamespace(channels=1, sample_rate=16000),
        logger=SimpleNamespace(event=Mock()),
    )


def test_optional_audio_is_private_with_permissive_umask_and_valid_wav(tmp_path):
    directory = tmp_path / "recordings"
    service = recording_service(directory)
    audio = b"\x00\x01" * 64
    previous = os.umask(0)
    try:
        FileCaptureMixin._save_pcm(service, audio)
    finally:
        os.umask(previous)
    files = list(directory.glob("*.wav"))
    assert len(files) == 1
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
    with wave.open(str(files[0]), "rb") as stream:
        assert stream.getnchannels() == 1
        assert stream.getframerate() == 16000
        assert stream.readframes(1000) == audio
    assert not list(directory.glob("*.tmp"))


def test_existing_public_recording_directory_is_refused_without_chmod(tmp_path):
    directory = tmp_path / "recordings"
    directory.mkdir()
    directory.chmod(0o755)
    old = directory / "old.wav"
    old.write_bytes(b"keep old recording")
    with pytest.raises(PermissionError, match="private_runtime_directory_required"):
        FileCaptureMixin._save_pcm(recording_service(directory), b"\x00\x00")
    assert old.read_bytes() == b"keep old recording"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o755
    assert list(directory.iterdir()) == [old]


def test_recording_collision_never_overwrites_previous_audio(tmp_path, monkeypatch):
    from apps.voice import svc_file_capture

    monkeypatch.setattr(svc_file_capture.time, "time_ns", lambda: 123)
    monkeypatch.setattr(svc_file_capture.secrets, "token_hex", lambda _size: "fixed")
    directory = tmp_path / "recordings"
    service = recording_service(directory)
    FileCaptureMixin._save_pcm(service, b"\x00\x01")
    output = next(directory.glob("*.wav"))
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        FileCaptureMixin._save_pcm(service, b"\x01\x02")
    assert output.read_bytes() == before
    assert list(directory.iterdir()) == [output]
