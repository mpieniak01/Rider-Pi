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


try:
    from common import provider_state
except ImportError:
    provider_state = None  # type: ignore


logger = logging.getLogger(__name__)

VISION_DOMAIN = "vision"


def _provider_mode() -> str:
    if provider_state is not None:
        try:
            return provider_state.get_domain_mode(VISION_DOMAIN)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Provider state read failed: %s", exc)
    return "pc" if get_mode() == "pc_offload" else "local"


def should_run_local_detectors() -> bool:
    """Check if local vision detectors (HOG, TFLite) should be active.

    Returns:
        True if running in local mode, False if in pc_offload mode
    """
    mode = _provider_mode()
    logger.debug(f"Vision provider mode: {mode}, local detectors: {mode == 'local'}")
    return mode != "pc"


def should_publish_frames_to_pc() -> bool:
    """Check if raw frames should be published to PC for processing.

    Returns:
        True if running in pc_offload mode, False otherwise
    """
    mode = _provider_mode()
    logger.debug(f"Vision provider mode: {mode}, publish frames: {mode == 'pc'}")
    return mode == "pc"


def log_vision_mode_status() -> None:
    """Log current vision mode status."""
    provider_mode = _provider_mode()
    mode = get_mode()
    if provider_mode == "local":
        logger.info(f"Vision provider mode: local (AI Mode {mode}) - Using local detectors")
    elif provider_mode == "pc":
        logger.info(f"Vision provider mode: pc (AI Mode {mode}) - Offloading to PC")
    else:
        logger.warning(f"Vision provider mode: {provider_mode} (AI Mode {mode}) - Unknown, defaulting to local")
