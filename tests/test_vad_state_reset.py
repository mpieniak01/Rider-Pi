"""Test VAD state reset functionality to prevent loop recording issues."""

import pytest

from apps.voice.vad import SilenceTail, WebRtcActivity


def test_silence_tail_reset():
    """Test that SilenceTail.reset() clears the window state."""
    tail = SilenceTail(frame_ms=20, tail_ms=100)  # 5 frame window
    
    # Fill window with silence indicators (False = silence detected)
    for _ in range(6):  # More than window size to ensure it's full
        result = tail.push(False)  # False = silence detected
    
    # At this point, window should be full and return True (end of speech detected)
    assert result is True, "Window should be full and detect end of speech"
    assert len(tail.window) == tail.limit, "Window should be at max capacity"
    
    # Reset should clear the window
    tail.reset()
    assert len(tail.window) == 0, "Window should be empty after reset"
    
    # After reset, should not immediately detect end of speech
    result = tail.push(False)  # First silence frame after reset
    assert result is False, "Should not detect end of speech immediately after reset"


def test_webrtc_activity_reset():
    """Test that WebRtcActivity.reset() properly resets internal state."""
    vad = WebRtcActivity(
        sample_rate=16000,
        mode=3,
        frame_ms=20,
        tail_ms=100,
        energy_gate=-40.0
    )
    
    # Simulate some silence detection that would fill the silence tail
    # Create a dummy frame (all zeros = silence, very low energy)
    silent_frame = b'\x00' * (16000 * 20 // 1000 * 2)  # 20ms at 16kHz, 16-bit
    
    # Fill the silence tail by calling VAD multiple times
    for _ in range(10):  # More than needed to fill the tail
        vad(silent_frame)
    
    # Reset should clear internal state
    vad.reset()
    
    # After reset, the VAD should be in a clean state
    # This is verified by checking that the tail window is empty
    assert len(vad.tail.window) == 0, "VAD tail window should be empty after reset"


def test_multiple_vad_cycles_without_reset():
    """Test that demonstrates the problem: VAD state persists between cycles."""
    # Note: In environments without webrtcvad, we need to simulate the problem manually
    # by directly manipulating the SilenceTail state
    vad = WebRtcActivity(
        sample_rate=16000,
        mode=3,
        frame_ms=20,
        tail_ms=100,
        energy_gate=-40.0
    )
    
    # Simulate the problem by directly filling the silence tail
    # In a real environment with webrtcvad, this would happen naturally
    for _ in range(6):  # Fill the tail window
        vad.tail.push(False)  # False = silence
    
    # At this point, the tail should indicate end of speech
    assert vad.tail.push(False) is True, "Should detect end of speech after silence frames"
    
    # Without reset, subsequent calls would immediately detect end of speech
    immediate_result = vad.tail.push(False)
    assert immediate_result is True, "This demonstrates the bug: immediate end detection"


def test_multiple_vad_cycles_with_reset():
    """Test that VAD reset fixes the multiple cycle issue."""
    vad = WebRtcActivity(
        sample_rate=16000,
        mode=3,
        frame_ms=20,
        tail_ms=100,
        energy_gate=-40.0
    )
    
    # Simulate the problem by directly filling the silence tail
    for _ in range(6):  # Fill the tail window
        vad.tail.push(False)  # False = silence
    
    assert vad.tail.push(False) is True, "Should detect end of speech after silence frames"
    
    # Reset VAD state before next recording cycle
    vad.reset()
    
    # Now the next "recording" should start fresh
    immediate_result = vad.tail.push(False)
    assert immediate_result is False, "Should not immediately detect end after reset"


def test_vad_behavior_with_webrtcvad_disabled():
    """Test VAD behavior when webrtcvad is not available (fallback mode)."""
    import apps.voice.vad as vad_module
    
    # Temporarily disable webrtcvad to test fallback behavior
    original_has_webrtc = vad_module._HAS_WEBRTC
    original_webrtcvad = vad_module.webrtcvad
    
    try:
        vad_module._HAS_WEBRTC = False
        vad_module.webrtcvad = None
        
        vad = WebRtcActivity(
            sample_rate=16000,
            mode=3,
            frame_ms=20,
            tail_ms=100,
            energy_gate=-40.0
        )
        
        # When webrtcvad is not available, VAD should return False
        silent_frame = b'\x00' * (16000 * 20 // 1000 * 2)
        result = vad(silent_frame)
        assert result is False, "VAD should return False when webrtcvad is not available"
        
        # Reset should still work even without webrtcvad
        vad.reset()
        assert len(vad.tail.window) == 0, "Reset should still work without webrtcvad"
        
    finally:
        # Restore original state
        vad_module._HAS_WEBRTC = original_has_webrtc
        vad_module.webrtcvad = original_webrtcvad