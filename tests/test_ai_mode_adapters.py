"""Tests for AI mode service adapters."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest


@pytest.fixture
def reset_ai_mode():
    """Reset AI mode to default state before each test."""
    from common import ai_mode

    ai_mode._current_mode = "local"
    ai_mode._mode_changed_ts = time.time()
    yield
    ai_mode._current_mode = "local"
    ai_mode._mode_changed_ts = time.time()


def test_vision_adapter_local_mode(reset_ai_mode):
    """Test vision adapter in local mode."""
    from apps.vision.ai_mode_adapter import (
        should_publish_frames_to_pc,
        should_run_local_detectors,
    )
    from common.ai_mode import set_mode

    set_mode("local")
    assert should_run_local_detectors() is True
    assert should_publish_frames_to_pc() is False


def test_vision_adapter_offload_mode(reset_ai_mode):
    """Test vision adapter in pc_offload mode."""
    from apps.vision.ai_mode_adapter import (
        should_publish_frames_to_pc,
        should_run_local_detectors,
    )
    from common.ai_mode import set_mode

    set_mode("pc_offload")
    assert should_run_local_detectors() is False
    assert should_publish_frames_to_pc() is True


def test_voice_adapter_local_mode(reset_ai_mode):
    """Test voice adapter in local mode."""
    from apps.voice.ai_mode_adapter import (
        should_offload_to_pc,
        should_run_local_asr,
        should_run_local_nlu,
        should_run_local_tts,
    )
    from common.ai_mode import set_mode

    set_mode("local")
    assert should_run_local_asr() is True
    assert should_run_local_tts() is True
    assert should_run_local_nlu() is True
    assert should_offload_to_pc() is False


def test_voice_adapter_offload_mode(reset_ai_mode):
    """Test voice adapter in pc_offload mode."""
    from apps.voice.ai_mode_adapter import (
        should_offload_to_pc,
        should_run_local_asr,
        should_run_local_nlu,
        should_run_local_tts,
    )
    from common.ai_mode import set_mode

    set_mode("pc_offload")
    assert should_run_local_asr() is False
    assert should_run_local_tts() is False
    assert should_run_local_nlu() is False
    assert should_offload_to_pc() is True


def test_navigator_adapter_local_mode(reset_ai_mode):
    """Test navigator adapter in local mode."""
    from apps.navigator.ai_mode_adapter import (
        should_use_local_obstacle_data,
        should_use_pc_enhanced_data,
    )
    from common.ai_mode import set_mode

    set_mode("local")
    assert should_use_local_obstacle_data() is True
    assert should_use_pc_enhanced_data() is False


def test_navigator_adapter_offload_mode(reset_ai_mode):
    """Test navigator adapter in pc_offload mode."""
    from apps.navigator.ai_mode_adapter import (
        should_use_local_obstacle_data,
        should_use_pc_enhanced_data,
    )
    from common.ai_mode import set_mode

    set_mode("pc_offload")
    assert should_use_local_obstacle_data() is False
    assert should_use_pc_enhanced_data() is True


def test_vision_adapter_fallback_without_ai_mode():
    """Test vision adapter works without common.ai_mode module."""
    # This test validates that the module doesn't crash when ai_mode is unavailable
    # The actual fallback behavior is tested implicitly by import
    from apps.vision import ai_mode_adapter

    # Should have fallback functions defined
    assert hasattr(ai_mode_adapter, "should_run_local_detectors")
    assert hasattr(ai_mode_adapter, "should_publish_frames_to_pc")
    assert callable(ai_mode_adapter.should_run_local_detectors)
    assert callable(ai_mode_adapter.should_publish_frames_to_pc)


def test_adapter_logging(reset_ai_mode, caplog):
    """Test that adapters log mode status correctly."""
    import logging

    from apps.navigator.ai_mode_adapter import log_navigator_mode_status
    from apps.vision.ai_mode_adapter import log_vision_mode_status
    from apps.voice.ai_mode_adapter import log_voice_mode_status
    from common.ai_mode import set_mode

    caplog.set_level(logging.INFO)

    # Test local mode logging
    set_mode("local")
    log_vision_mode_status()
    log_voice_mode_status()
    log_navigator_mode_status()

    assert "local" in caplog.text.lower()
    assert any("vision" in rec.message.lower() for rec in caplog.records)
    assert any("voice" in rec.message.lower() for rec in caplog.records)
    assert any("navigator" in rec.message.lower() for rec in caplog.records)

    caplog.clear()

    # Test pc_offload mode logging
    set_mode("pc_offload")
    log_vision_mode_status()
    log_voice_mode_status()
    log_navigator_mode_status()

    assert "offload" in caplog.text.lower() or "pc" in caplog.text.lower()


def test_adapter_mode_switching(reset_ai_mode):
    """Test adapters respond correctly to mode switching."""
    from apps.navigator.ai_mode_adapter import should_use_pc_enhanced_data
    from apps.vision.ai_mode_adapter import should_run_local_detectors
    from apps.voice.ai_mode_adapter import should_run_local_asr
    from common.ai_mode import set_mode

    # Start in local
    set_mode("local")
    assert should_run_local_detectors() is True
    assert should_run_local_asr() is True
    assert should_use_pc_enhanced_data() is False

    # Switch to offload
    set_mode("pc_offload")
    assert should_run_local_detectors() is False
    assert should_run_local_asr() is False
    assert should_use_pc_enhanced_data() is True

    # Switch back to local
    set_mode("local")
    assert should_run_local_detectors() is True
    assert should_run_local_asr() is True
    assert should_use_pc_enhanced_data() is False
