"""Vision service AI mode integration.

This module provides utilities for vision services to adapt their behavior
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


def should_run_local_detectors() -> bool:
    """Check if local vision detectors (HOG, TFLite) should be active.

    Returns:
        True if running in local mode, False if in pc_offload mode
    """
    mode = get_mode()
    logger.debug(f"AI mode check: {mode}, local detectors: {mode == 'local'}")
    return mode == "local"


def should_publish_frames_to_pc() -> bool:
    """Check if raw frames should be published to PC for processing.

    Returns:
        True if running in pc_offload mode, False otherwise
    """
    mode = get_mode()
    logger.debug(f"AI mode check: {mode}, publish frames: {mode == 'pc_offload'}")
    return mode == "pc_offload"


def log_vision_mode_status() -> None:
    """Log current vision mode status."""
    mode = get_mode()
    if is_local():
        logger.info(f"Vision AI Mode: {mode} - Using local detectors (HOG, TFLite)")
    elif is_offload():
        logger.info(f"Vision AI Mode: {mode} - Offloading to PC via ZMQ")
    else:
        logger.warning(f"Vision AI Mode: {mode} - Unknown mode, defaulting to local")
