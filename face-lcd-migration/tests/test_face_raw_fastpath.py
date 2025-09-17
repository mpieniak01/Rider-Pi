import os
import pytest
from PIL import Image
from apps.ui.face.driver import make_driver
from apps.ui.face.panel_cfg import PanelCfg
from apps.ui.face.face_io import to_rgb565, apply_rotate, fit_strategy

@pytest.fixture
def mock_driver():
    cfg = PanelCfg(rotate=0, bgr=False, mx=False, mv=False)
    driver = make_driver("mock", cfg)
    yield driver

def test_rgb565_buffer_size(mock_driver):
    img = Image.new("RGB", (100, 100), color="red")
    rgb565_data = to_rgb565(img)
    assert len(rgb565_data) == 100 * 100 * 2  # 2 bytes per pixel for RGB565

def test_apply_rotate(mock_driver):
    img = Image.new("RGB", (100, 100), color="blue")
    rotated_img = apply_rotate(img, 90)
    assert rotated_img.size == (100, 100)  # Size should remain the same
    assert rotated_img.getpixel((0, 0)) == (0, 0, 255)  # Check color at a corner

def test_fit_strategy_fill(mock_driver):
    img = Image.new("RGB", (50, 50), color="green")
    fitted_img = fit_strategy(img, "fill")
    assert fitted_img.size == (100, 100)  # Should fill the target size

def test_metadata_and_mock_files(mock_driver):
    img = Image.new("RGB", (100, 100), color="yellow")
    mock_driver.push_png(img)
    mock_driver.push_rgb565(to_rgb565(img), 100, 100)

    assert os.path.exists("/tmp/face_last.png")
    assert os.path.exists("/tmp/face_last.rgb565")
    assert os.path.exists("/tmp/face_last.meta.json")