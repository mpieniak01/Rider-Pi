from __future__ import annotations

"""
Fabryka driverów LCD buźki: mock (domyślny), spi (opcjonalny).

DEPRECATED: This module is kept for backward compatibility.
Please use drivers.lcd instead.
"""

from typing import Literal

# Re-export from new location
from drivers.lcd import Driver, PanelCfg, make_driver

__all__ = ["Driver", "make_driver", "PanelCfg"]
