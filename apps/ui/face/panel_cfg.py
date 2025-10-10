from __future__ import annotations

"""
Panel configuration for LCD display.

DEPRECATED: This module is kept for backward compatibility.
Please use drivers.lcd.PanelCfg instead.
"""

# Re-export from new location
from drivers.lcd.panel_cfg import PanelCfg

__all__ = ["PanelCfg"]
