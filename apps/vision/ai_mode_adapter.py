"""Vision service AI mode integration.

This module provides utilities for vision services to adapt their behavior
based on the current AI processing mode (local vs pc_offload).
"""

from __future__ import annotations

import logging
import math
import os
import time
from pathlib import Path

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
PC_HEALTH_STALE_SEC = float(os.getenv("VISION_PC_HEALTH_STALE_SEC", "8.0"))


def _pc_ready() -> bool:
    if provider_state is None:
        return False
    try:
        health = provider_state.get_pc_health()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Provider state health read failed: %s", exc)
        return False
    if not isinstance(health, dict) or not health:
        return False
    if health.get("reachable") is not True or health.get("stale") is True:
        return False
    status = str(health.get("status") or "").lower()
    if status in {"offline", "error"}:
        return False
    updated = health.get("updated_ts") or 0.0
    try:
        updated_ts = float(updated)
    except (TypeError, ValueError):
        updated_ts = 0.0
    return math.isfinite(updated_ts) and updated_ts > 0 and -0.1 <= time.time() - updated_ts <= PC_HEALTH_STALE_SEC


def _provider_mode() -> str:
    ai_override = "pc" if get_mode() == "pc_offload" else "local"
    provider_mode: str | None = None

    if provider_state is not None:
        state_file = getattr(provider_state, "STATE_FILE", None)
        if isinstance(state_file, (str, Path)) and not Path(state_file).exists():
            return ai_override
        try:
            mode = provider_state.get_domain_mode(VISION_DOMAIN)
            if mode in {"local", "pc"}:
                provider_mode = mode
        except Exception as exc:  # noqa: BLE001
            logger.debug("Provider state read failed: %s", exc)

        return provider_mode or "unknown"
    return ai_override


def should_run_local_detectors() -> bool:
    """Check if local vision detectors (HOG, TFLite) should be active.

    Returns:
        True if running in local mode, False if in pc_offload mode
    """
    mode = _provider_mode()
    if mode == "unknown":
        return False
    if mode == "local":
        logger.debug("Vision provider mode=%s -> local detectors enabled", mode)
        return True

    if not _pc_ready():
        logger.info("Vision provider PC mode requested but health is offline/stale -> running local detectors")
        return True

    logger.debug("Vision provider PC mode active -> local detectors disabled")
    return False


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
