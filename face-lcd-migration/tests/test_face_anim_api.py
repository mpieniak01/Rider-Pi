import pytest
from apps.ui.face.driver import make_driver
from apps.ui.face.panel_cfg import PanelCfg

@pytest.fixture
def driver():
    cfg = PanelCfg(rotate=0, bgr=False, mx=False, mv=False)
    return make_driver("mock", cfg)

def test_face_animation(driver):
    # Test the animation functionality of the face driver
    # This is a placeholder for the actual animation test logic
    assert driver is not None

def test_push_png(driver):
    # Test pushing a PNG image to the driver
    image = ...  # Load or create a test image
    driver.push_png(image)
    # Verify the image was saved correctly
    assert ...  # Add assertions to check the saved PNG

def test_push_rgb565(driver):
    # Test pushing RGB565 bytes to the driver
    rgb565_data = ...  # Generate or load test RGB565 data
    width, height = ...  # Set the dimensions of the image
    driver.push_rgb565(rgb565_data, width, height)
    # Verify the RGB565 data was saved correctly
    assert ...  # Add assertions to check the saved RGB565 data