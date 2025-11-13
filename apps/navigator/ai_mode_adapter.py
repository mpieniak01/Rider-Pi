"""Navigator service AI mode integration.

This module provides utilities for navigator to adapt its behavior
based on the current AI processing mode (local vs pc_offload).
"""

from __future__ import annotations

import logging

try:
    from common.ai_mode import get_mode, is_local, is_offload
except ImportError:
    # Fallback if common.ai_mode is not available
    def get_mode():  # type: ignore
        return "local"

    def is_local():  # type: ignore
        return True

    def is_offload():  # type: ignore
        return False


logger = logging.getLogger(__name__)


def should_use_local_obstacle_data() -> bool:
    """Check if navigator should use local obstacle detection data.

    Returns:
        True if running in local mode, False if in pc_offload mode
    """
    mode = get_mode()
    logger.debug(f"AI mode check: {mode}, use local obstacles: {mode == 'local'}")
    return mode == "local"


def should_use_pc_enhanced_data() -> bool:
    """Check if navigator should use PC-enhanced obstacle data.

    In pc_offload mode, navigator should subscribe to vision.obstacle.enhanced
    topic for obstacle data processed by PC.

    Returns:
        True if running in pc_offload mode, False otherwise
    """
    mode = get_mode()
    logger.debug(f"AI mode check: {mode}, use PC enhanced data: {mode == 'pc_offload'}")
    return mode == "pc_offload"


def log_navigator_mode_status() -> None:
    """Log current navigator mode status."""
    mode = get_mode()
    if is_local():
        logger.info(f"Navigator AI Mode: {mode} - Using local obstacle detection")
    elif is_offload():
        logger.info(f"Navigator AI Mode: {mode} - Using PC-enhanced obstacle data")
    else:
        logger.warning(f"Navigator AI Mode: {mode} - Unknown mode, defaulting to local")
