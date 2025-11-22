"""Voice service AI mode integration.

This module provides utilities for voice services to adapt their behavior
based on the current AI processing mode (local vs pc_offload).
"""

from __future__ import annotations

import logging
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
VOICE_DOMAIN = "voice"


def _provider_mode() -> str:
    ai_override = "pc" if get_mode() == "pc_offload" else "local"
    provider_mode: str | None = None

    if provider_state is not None:
        state_file = getattr(provider_state, "STATE_FILE", None)
        state_path = Path(state_file) if isinstance(state_file, (str, Path)) else None
        # If the registry file is present, respect its configuration. Otherwise,
        # fall back to the classic AI mode switch so CI/local setups without
        # provider control still behave correctly.
        if state_path is None or state_path.exists():
            try:
                mode = provider_state.get_domain_mode(VOICE_DOMAIN)
                if mode in {"local", "pc"}:
                    provider_mode = mode
            except Exception as exc:  # noqa: BLE001
                logger.debug("Provider state read failed: %s", exc)

    # AI mode overrides provider: local must stay local; pc_offload forces pc.
    if ai_override == "pc":
        return "pc"
    if ai_override == "local":
        return "local"

    if provider_mode == "local":
        return "local"

    if provider_mode == "pc":
        return "pc"

    return "local"


def should_run_local_asr() -> bool:
    """Check if local ASR (Automatic Speech Recognition) should be active.

    Returns:
        True if running in local mode, False if in pc_offload mode
    """
    mode = _provider_mode()
    logger.debug(f"Voice provider mode: {mode}, local ASR: {mode != 'pc'}")
    return mode != "pc"


def should_run_local_tts() -> bool:
    """Check if local TTS (Text-to-Speech) should be active.

    Returns:
        True if running in local mode, False if in pc_offload mode
    """
    mode = _provider_mode()
    logger.debug(f"Voice provider mode: {mode}, local TTS: {mode != 'pc'}")
    return mode != "pc"


def should_run_local_nlu() -> bool:
    """Check if local NLU (Natural Language Understanding) should be active.

    Returns:
        True if running in local mode, False if in pc_offload mode
    """
    mode = _provider_mode()
    logger.debug(f"Voice provider mode: {mode}, local NLU: {mode != 'pc'}")
    return mode != "pc"


def should_offload_to_pc() -> bool:
    """Check if voice processing should be offloaded to PC.

    Returns:
        True if running in pc_offload mode, False otherwise
    """
    mode = _provider_mode()
    logger.debug(f"Voice provider mode: {mode}, offload to PC: {mode == 'pc'}")
    return mode == "pc"


def log_voice_mode_status() -> None:
    """Log current voice mode status."""
    provider_mode = _provider_mode()
    mode = get_mode()
    if provider_mode == "local":
        logger.info(f"Voice provider mode: local (AI Mode {mode}) - Using local ASR/TTS/NLU engines")
    elif provider_mode == "pc":
        logger.info(f"Voice provider mode: pc (AI Mode {mode}) - Offloading ASR/TTS/NLU to PC")
    else:
        logger.warning(f"Voice provider mode: {provider_mode} (AI Mode {mode}) - Unknown, defaulting to local")
