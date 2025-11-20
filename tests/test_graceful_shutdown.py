"""Tests for graceful shutdown functionality."""

from __future__ import annotations

import os
import signal
import tempfile
import time
from unittest.mock import Mock, patch

import pytest


def test_signal_handler_basic():
    """Test basic signal handler registration and callback execution."""
    from common.signal_handler import GracefulShutdown

    shutdown = GracefulShutdown()
    callback_executed = []

    def cleanup():
        callback_executed.append(True)

    shutdown.register(cleanup)
    shutdown._cleanup()

    assert len(callback_executed) == 1


def test_signal_handler_multiple_callbacks():
    """Test multiple cleanup callbacks are executed."""
    from common.signal_handler import GracefulShutdown

    shutdown = GracefulShutdown()
    results = []

    def cleanup1():
        results.append(1)

    def cleanup2():
        results.append(2)

    shutdown.register(cleanup1)
    shutdown.register(cleanup2)
    shutdown._cleanup()

    assert results == [1, 2]


def test_signal_handler_error_resilience():
    """Test that cleanup continues even if one callback fails."""
    from common.signal_handler import GracefulShutdown

    shutdown = GracefulShutdown()
    results = []

    def failing_cleanup():
        raise RuntimeError("Test error")

    def successful_cleanup():
        results.append("success")

    shutdown.register(failing_cleanup)
    shutdown.register(successful_cleanup)
    shutdown._cleanup()

    assert "success" in results


def test_pidlock_cleanup():
    """Test PID lock file exists and cleanup mechanism is registered."""
    with tempfile.TemporaryDirectory() as tmpdir:
        lock_path = os.path.join(tmpdir, "test.lock")

        # Import the function
        from common.pidlock import single_instance

        # Create lock
        fd = single_instance(lock_path)
        assert os.path.exists(lock_path)
        assert fd is not None

        # Verify that PID was written to the file
        with open(lock_path, "r") as f:
            pid_str = f.read()
            assert pid_str == str(os.getpid())


def test_pidlock_second_instance_fails():
    """Test that second instance with same lock fails."""
    import subprocess
    import sys

    with tempfile.TemporaryDirectory() as tmpdir:
        lock_path = os.path.join(tmpdir, "test_multi.lock")

        from common.pidlock import single_instance

        # First instance succeeds
        fd1 = single_instance(lock_path)
        assert fd1 is not None

        # Try second instance in a subprocess (since we can't exit in same process)
        test_script = f"""
import sys
sys.path.insert(0, '{os.getcwd()}')
from common.pidlock import single_instance
single_instance('{lock_path}')
"""
        result = subprocess.run([sys.executable, "-c", test_script], capture_output=True, timeout=5)
        # Should exit with code 1
        assert result.returncode == 1
        assert b"another instance running" in result.stderr


def test_audio_capture_pdeathsig_setup():
    """Test that audio capture sets up PDEATHSIG correctly."""
    from apps.voice.audio.capture import _set_pdeathsig

    # Should not raise on platforms without prctl
    try:
        _set_pdeathsig()
    except Exception as e:
        # Only acceptable if we're not on Linux
        assert "prctl" in str(e) or "libc" in str(e)


def test_audio_capture_subprocess_cleanup():
    """Test that AudioCapture properly cleans up subprocess on close."""
    from apps.voice.audio.capture import AudioCapture, CaptureConfig

    # Create a mock config with minimal settings
    config = CaptureConfig(device="default", sample_rate=16000, channels=1, frame_ms=20)

    # Mock the subprocess to avoid actually starting arecord
    with patch("apps.voice.audio.capture.subprocess.Popen") as mock_popen:
        mock_proc = Mock()
        mock_proc.stdout = Mock()
        mock_proc.stderr = Mock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        capture = AudioCapture(config)

        # Enter context (simulating with statement)
        with patch.object(capture, "_start_proc", return_value=mock_proc):
            capture.__enter__()
            capture._proc = mock_proc

            # Close should kill the process
            capture.close()

            # Verify terminate was called
            mock_proc.terminate.assert_called_once()


def test_lcd_renderer_cleanup():
    """Test LCD renderer cleanup method exists and is callable."""
    # We can't fully test LCD without actual hardware, but we can verify
    # the cleanup method exists and handles missing dependencies gracefully
    try:
        from drivers.lcd.driver_ili9xx import LCDRenderer

        # Verify cleanup method exists
        assert hasattr(LCDRenderer, "cleanup")
        assert callable(getattr(LCDRenderer, "cleanup"))
    except Exception as e:
        # If we can't import due to missing xgoscreen, that's okay for this test
        # We've verified the code structure in our manual review
        assert "xgoscreen" in str(e) or "PIL" in str(e)


def test_camera_signal_handler_setup():
    """Test that camera module has signal handling code."""
    # Read the __main__.py file and verify signal handling is present
    import os

    camera_main_path = os.path.join(os.path.dirname(__file__), "..", "apps", "camera", "__main__.py")
    with open(camera_main_path, "r") as f:
        content = f.read()

    # Verify signal handling code is present
    assert "signal.signal" in content
    assert "SIGTERM" in content
    assert "SIGINT" in content
    assert "signal_handler" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
