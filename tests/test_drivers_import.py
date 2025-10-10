#!/usr/bin/env python3
"""
Test that driver imports work correctly after refactoring.
"""

import sys
import unittest


class TestDriverImports(unittest.TestCase):
    """Test driver layer imports."""

    def test_xgo_driver_import(self):
        """Test importing XGO driver from new location."""
        from drivers.xgo import XgoAdapter

        self.assertIsNotNone(XgoAdapter)

    def test_xgo_backward_compat(self):
        """Test backward compatibility for XGO driver."""
        from apps.motion.xgo_adapter import XgoAdapter

        self.assertIsNotNone(XgoAdapter)

    def test_lcd_panel_cfg_import(self):
        """Test importing PanelCfg from new location."""
        from drivers.lcd import PanelCfg

        self.assertIsNotNone(PanelCfg)
        # Test instantiation
        cfg = PanelCfg(rotate=90, bgr=True)
        self.assertEqual(cfg.rotate, 90)
        self.assertTrue(cfg.bgr)

    def test_lcd_panel_cfg_backward_compat(self):
        """Test backward compatibility for PanelCfg."""
        from apps.ui.face.panel_cfg import PanelCfg

        self.assertIsNotNone(PanelCfg)

    def test_lcd_driver_factory(self):
        """Test LCD driver factory function."""
        from drivers.lcd import make_driver

        self.assertIsNotNone(make_driver)

    def test_lcd_driver_factory_backward_compat(self):
        """Test backward compatibility for driver factory."""
        from apps.ui.face.driver import make_driver

        self.assertIsNotNone(make_driver)


if __name__ == "__main__":
    unittest.main()
