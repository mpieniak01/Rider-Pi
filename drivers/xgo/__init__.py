"""
XGO Robot Driver

Hardware driver for XGO robot platform.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Union

from .adapter import XgoAdapter

if TYPE_CHECKING:
    from .sim import SimulatedXgoAdapter


RobotDriver = Union[XgoAdapter, "SimulatedXgoAdapter"]


def get_robot_driver() -> RobotDriver:
    """
    Factory function to get the appropriate robot driver.

    Returns physical driver by default, or simulated driver if RIDER_SIMULATOR=1.

    Returns:
        XgoAdapter or SimulatedXgoAdapter instance
    """
    if os.getenv("RIDER_SIMULATOR", "0") == "1":
        from .sim import SimulatedXgoAdapter

        return SimulatedXgoAdapter()
    else:
        return XgoAdapter()


__all__ = ["XgoAdapter", "get_robot_driver"]
