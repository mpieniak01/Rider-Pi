"""Voice service AI mode integration.

This module provides utilities for voice services to adapt their behavior
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


def should_run_local_asr() -> bool:
    """Check if local ASR (Automatic Speech Recognition) should be active.

    Returns:
        True if running in local mode, False if in pc_offload mode
    """
    mode = get_mode()
    logger.debug(f"AI mode check: {mode}, local ASR: {mode == 'local'}")
    return mode == "local"


def should_run_local_tts() -> bool:
    """Check if local TTS (Text-to-Speech) should be active.

    Returns:
        True if running in local mode, False if in pc_offload mode
    """
    mode = get_mode()
    logger.debug(f"AI mode check: {mode}, local TTS: {mode == 'local'}")
    return mode == "local"


def should_run_local_nlu() -> bool:
    """Check if local NLU (Natural Language Understanding) should be active.

    Returns:
        True if running in local mode, False if in pc_offload mode
    """
    mode = get_mode()
    logger.debug(f"AI mode check: {mode}, local NLU: {mode == 'local'}")
    return mode == "local"


def should_offload_to_pc() -> bool:
    """Check if voice processing should be offloaded to PC.

    Returns:
        True if running in pc_offload mode, False otherwise
    """
    mode = get_mode()
    logger.debug(f"AI mode check: {mode}, offload to PC: {mode == 'pc_offload'}")
    return mode == "pc_offload"


def log_voice_mode_status() -> None:
    """Log current voice mode status."""
    mode = get_mode()
    if is_local():
        logger.info(f"Voice AI Mode: {mode} - Using local ASR/TTS/NLU engines")
    elif is_offload():
        logger.info(f"Voice AI Mode: {mode} - Offloading ASR/TTS/NLU to PC via ZMQ")
    else:
        logger.warning(f"Voice AI Mode: {mode} - Unknown mode, defaulting to local")
