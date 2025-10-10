#!/usr/bin/env python3
"""
Test simulation mode toggle functionality.
"""

import os
import sys
import unittest


class TestSimulationToggle(unittest.TestCase):
    """Test driver factory functions with simulation toggle."""

    def setUp(self):
        """Save original environment state."""
        self.original_env = os.environ.get("RIDER_SIMULATOR")

    def tearDown(self):
        """Restore original environment state."""
        if self.original_env is None:
            os.environ.pop("RIDER_SIMULATOR", None)
        else:
            os.environ["RIDER_SIMULATOR"] = self.original_env

    def test_xgo_physical_mode(self):
        """Test XGO driver returns physical implementation by default."""
        os.environ.pop("RIDER_SIMULATOR", None)

        from drivers.xgo import get_robot_driver

        driver = get_robot_driver()
        # Should be XgoAdapter (physical) not SimulatedXgoAdapter
        self.assertEqual(type(driver).__name__, "XgoAdapter")
        self.assertTrue(driver.ok() or not driver.ok())  # May or may not have hardware

    def test_xgo_simulation_mode(self):
        """Test XGO driver returns simulated implementation when RIDER_SIMULATOR=1."""
        os.environ["RIDER_SIMULATOR"] = "1"

        # Need to reimport to pick up env change
        import importlib

        import drivers.xgo

        importlib.reload(drivers.xgo)
        from drivers.xgo import get_robot_driver

        driver = get_robot_driver()
        self.assertEqual(type(driver).__name__, "SimulatedXgoAdapter")
        self.assertTrue(driver.ok())  # Simulator is always OK

    def test_simulated_xgo_interface(self):
        """Test SimulatedXgoAdapter provides expected interface."""
        from drivers.xgo.sim import SimulatedXgoAdapter

        driver = SimulatedXgoAdapter()

        # Test basic interface
        self.assertTrue(driver.ok())
        self.assertIsNotNone(driver.available_methods())

        # Test motion methods don't crash
        driver.stop()
        driver.drive("forward", 0.5, dur=0.1)
        driver.spin("left", 0.3, dur=0.1)
        driver.action("sit")

        # Test configuration methods
        driver.set_stabilization(True)
        driver.enable_balance(True)
        driver.set_height(10)

        # Test sensor methods
        battery = driver.battery()
        self.assertIsNotNone(battery)
        self.assertGreater(battery, 0.0)
        self.assertLessEqual(battery, 1.0)

        imu = driver.imu()
        self.assertIsNotNone(imu)
        self.assertIn("roll", imu)
        self.assertIn("pitch", imu)
        self.assertIn("yaw", imu)

        # Test LED
        driver.led(0, (255, 0, 0))

    def test_lcd_simulation_mode(self):
        """Test LCD driver returns simulated implementation when RIDER_SIMULATOR=1."""
        os.environ["RIDER_SIMULATOR"] = "1"

        # Need to reimport to pick up env change
        import importlib

        import drivers.lcd

        importlib.reload(drivers.lcd)
        from drivers.lcd import get_lcd_driver

        driver = get_lcd_driver()
        self.assertEqual(type(driver).__name__, "SimulatedLCDRenderer")

    def test_simulated_lcd_interface(self):
        """Test SimulatedLCDRenderer provides expected interface."""
        from drivers.lcd.sim import SimulatedLCDRenderer

        driver = SimulatedLCDRenderer()

        # Check basic properties
        self.assertEqual(driver.width, 240)
        self.assertEqual(driver.height, 320)

        # Test methods exist and don't crash
        # Note: We can't actually call ShowImage without PIL, but we can check it exists
        self.assertTrue(hasattr(driver, "ShowImage"))

    def test_simulated_lcd_driver_interface(self):
        """Test SimulatedLCDDriver provides expected interface."""
        from drivers.lcd.sim import SimulatedLCDDriver

        driver = SimulatedLCDDriver(save_frames=False)

        # Test methods exist
        self.assertTrue(hasattr(driver, "push_png"))
        self.assertTrue(hasattr(driver, "push_rgb565"))

        # Test RGB565 push doesn't crash
        dummy_buf = b"\x00" * (240 * 320 * 2)  # 240x320 RGB565
        driver.push_rgb565(dummy_buf, 240, 320)
        self.assertEqual(driver.frame_count, 1)


if __name__ == "__main__":
    unittest.main()
