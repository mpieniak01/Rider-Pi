"""Legacy PNG/RGB565 artifacts stay compatible without following attacker links."""

from __future__ import annotations

import json
import os
import stat
from types import SimpleNamespace

import pytest
from PIL import Image

from apps.ui.face.driver.mock import MockFaceDriver as LegacyMock
from drivers.lcd.mock import MockFaceDriver
from drivers.lcd.sim import SimulatedLCDDriver


@pytest.fixture(params=[MockFaceDriver, SimulatedLCDDriver])
def driver(request, tmp_path):
    instance = request.param(SimpleNamespace(as_dict=lambda: {"rotate": 270}))
    instance.out_base = tmp_path / "preview"
    return instance


def artifact_base(driver):
    suffix = "_0001" if isinstance(driver, SimulatedLCDDriver) else ""
    return str(driver.out_base) + suffix


def push(driver, mode):
    if mode == "png":
        driver.push_png(Image.new("RGB", (2, 2), "red"))
    else:
        driver.push_rgb565(b"\xf8\x00" * 4, 2, 2)


def test_legacy_mock_import_is_the_same_secure_driver():
    assert LegacyMock is MockFaceDriver


@pytest.mark.parametrize("mode", ["png", "rgb565"])
@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_all_artifacts_replace_links_without_touching_victims(driver, tmp_path, mode, link_kind):
    victim = tmp_path / "private"
    victim.write_bytes(b"keep-private")
    extensions = [".png", ".meta.json"]
    if mode == "rgb565":
        extensions.append(".rgb565")
    base = artifact_base(driver)
    for extension in extensions:
        output = tmp_path / (base + extension)
        if link_kind == "symlink":
            output.symlink_to(victim)
        else:
            os.link(victim, output)
    old_mask = os.umask(0)
    try:
        push(driver, mode)
    finally:
        os.umask(old_mask)
    assert victim.read_bytes() == b"keep-private"
    for extension in extensions:
        output = tmp_path / (base + extension)
        assert not output.is_symlink()
        assert output.stat().st_nlink == 1
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with Image.open(base + ".png") as image:
        assert image.size == (2, 2)
    metadata = json.loads((tmp_path / (base + ".meta.json")).read_text())
    assert metadata["mode"] == mode
    assert metadata["size"] == [2, 2]
    assert metadata["panel"]["rotate"] == 270
    if mode == "rgb565":
        assert (tmp_path / (base + ".rgb565")).read_bytes() == b"\xf8\x00" * 4
    assert not list(tmp_path.glob(".rider-write-*"))


@pytest.mark.parametrize("mode", ["png", "rgb565"])
@pytest.mark.parametrize("unsafe_parent", ["symlink", "public"])
def test_untrusted_parent_never_receives_artifacts(driver, tmp_path, caplog, mode, unsafe_parent):
    target = tmp_path / "destination"
    target.mkdir()
    if unsafe_parent == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(target, target_is_directory=True)
        driver.out_base = alias / "preview"
    else:
        target.chmod(0o777)
        driver.out_base = target / "preview"
    if isinstance(driver, SimulatedLCDDriver):
        push(driver, mode)
        assert "Failed to save frame" in caplog.text
    else:
        with pytest.raises(OSError):
            push(driver, mode)
    assert not list(target.iterdir())


def test_failed_encoder_preserves_previous_image_and_cleans_temporary(driver, tmp_path, caplog):
    output = tmp_path / (artifact_base(driver) + ".png")
    output.write_bytes(b"previous-image")

    def fail(stream, _format):
        stream.write(b"incomplete")
        raise RuntimeError("encoder failed")

    image = SimpleNamespace(size=(2, 2), save=fail)
    if isinstance(driver, SimulatedLCDDriver):
        driver.push_png(image)
        assert "encoder failed" in caplog.text
    else:
        with pytest.raises(RuntimeError, match="encoder failed"):
            driver.push_png(image)
    assert output.read_bytes() == b"previous-image"
    assert not list(tmp_path.glob(".rider-write-*"))
    assert not (tmp_path / (artifact_base(driver) + ".meta.json")).exists()


def test_rgb565_and_metadata_remain_available_without_optional_numpy(driver, monkeypatch, tmp_path):
    import sys

    monkeypatch.setitem(sys.modules, "numpy", None)
    push(driver, "rgb565")
    base = artifact_base(driver)
    assert (tmp_path / (base + ".rgb565")).read_bytes() == b"\xf8\x00" * 4
    assert json.loads((tmp_path / (base + ".meta.json")).read_text())["mode"] == "rgb565"
    assert not (tmp_path / (base + ".png")).exists()


def test_simulator_without_capture_never_creates_files(tmp_path):
    driver = SimulatedLCDDriver(save_frames=False)
    driver.out_base = tmp_path / "missing" / "preview"
    push(driver, "png")
    push(driver, "rgb565")
    assert driver.frame_count == 2
    assert not list(tmp_path.iterdir())
