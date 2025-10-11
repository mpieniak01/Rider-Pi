from __future__ import annotations

import warnings

from drivers.lcd.driver_ili9xx import *  # noqa: F401,F403

warnings.warn(
    "apps.ui.face.driver_ili9xx is deprecated; use drivers.lcd.driver_ili9xx instead.",
    DeprecationWarning,
    stacklevel=2,
)
