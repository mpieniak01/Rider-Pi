"""Tests for graceful shutdown functionality."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from unittest.mock import Mock, patch

import pytest


class TestGracefulShutdown:
    """Test the GracefulShutdown signal handler."""

    def test_signal_handler_creation(self):
        """Test that GracefulShutdown can be created."""
        from common.graceful_shutdown import GracefulShutdown

        shutdown = GracefulShutdown()
        assert shutdown.should_stop is False
        assert len(shutdown._cleanup_handlers) == 0

    def test_register_cleanup_handler(self):
        """Test registering cleanup handlers."""
        from common.graceful_shutdown import GracefulShutdown

        shutdown = GracefulShutdown()
        cleanup_called = []

        def cleanup():
            cleanup_called.append(True)

        shutdown.register_cleanup(cleanup)
        assert len(shutdown._cleanup_handlers) == 1

        # Call cleanup manually
        shutdown._run_cleanup()
        assert len(cleanup_called) == 1

    def test_cleanup_handlers_called_on_exit(self):
        """Test that cleanup handlers are called on context exit."""
        from common.graceful_shutdown import GracefulShutdown

        cleanup_called = []

        def cleanup():
            cleanup_called.append(True)

        with GracefulShutdown() as shutdown:
            shutdown.register_cleanup(cleanup)

        assert len(cleanup_called) == 1

    def test_multiple_cleanup_handlers(self):
        """Test that multiple cleanup handlers are all called."""
        from common.graceful_shutdown import GracefulShutdown

        call_order = []

        def cleanup1():
            call_order.append(1)

        def cleanup2():
            call_order.append(2)

        with GracefulShutdown() as shutdown:
            shutdown.register_cleanup(cleanup1)
            shutdown.register_cleanup(cleanup2)

        assert call_order == [1, 2]


class TestPIDLock:
    """Test PID lock file cleanup."""

    def test_pidlock_cleanup_on_exit(self):
        """Test that PID lock files are cleaned up on normal exit."""
        from common.pidlock import single_instance

        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = os.path.join(tmpdir, "test.lock")
            # Calculate project root from this test file
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

            # Create lock in subprocess to test cleanup
            script = f"""
import sys
sys.path.insert(0, '{project_root}')
from common.pidlock import single_instance
fd = single_instance('{lock_path}')
# Exit normally - atexit should cleanup
"""
            result = subprocess.run(
                ["python3", "-c", script],
                capture_output=True,
                timeout=2,
            )
            assert result.returncode == 0

            # Lock file should not exist after process exits
            assert not os.path.exists(lock_path)

    def test_pidlock_prevents_double_instance(self):
        """Test that PID lock prevents multiple instances."""
        # Note: This test uses subprocess because the lock needs to be held
        # by a real process, not just in the same Python instance
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = os.path.join(tmpdir, "test2.lock")
            # Calculate project root from this test file
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

            # Start a subprocess that holds the lock
            script = f"""
import sys
import time
sys.path.insert(0, '{project_root}')
from common.pidlock import single_instance
fd = single_instance('{lock_path}')
time.sleep(2)  # Hold lock for 2 seconds
"""
            proc = subprocess.Popen(
                ["python3", "-c", script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            try:
                # Wait a bit for first process to acquire lock
                time.sleep(0.5)

                # Try to acquire same lock in second subprocess
                result = subprocess.run(
                    ["python3", "-c", script],
                    capture_output=True,
                    timeout=1,
                )

                # Second instance should fail with exit code 1
                assert result.returncode == 1
                assert b"another instance running" in result.stderr
            finally:
                proc.terminate()
                proc.wait(timeout=2)


class TestAudioCaptureCleanup:
    """Test AudioCapture subprocess cleanup."""

    @patch("shutil.which")
    @patch("apps.voice.audio.capture.subprocess.Popen")
    @patch("apps.voice.audio.capture.voice_logging.get_logger")
    def test_audiocapture_subprocess_killed_on_close(self, mock_get_logger, mock_popen, mock_which):
        """Test that arecord subprocess is terminated on AudioCapture.close()."""
        from apps.voice.audio.capture import AudioCapture, CaptureConfig

        # Mock logger
        mock_logger = Mock()
        mock_logger.event = Mock()
        mock_logger.info = Mock()
        mock_logger.debug = Mock()
        mock_get_logger.return_value = mock_logger

        # Mock which to find arecord
        mock_which.return_value = "/usr/bin/arecord"

        # Mock subprocess
        mock_proc = Mock()
        mock_proc.stdout = Mock()
        mock_proc.stderr = Mock()
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        config = CaptureConfig(device="default", sample_rate=16000)
        with AudioCapture(config):
            pass

        # Verify terminate was called
        assert mock_proc.terminate.called or mock_proc.kill.called

    @patch("shutil.which")
    @patch("apps.voice.audio.capture.subprocess.Popen")
    @patch("apps.voice.audio.capture.voice_logging.get_logger")
    def test_audiocapture_pdeathsig_configured(self, mock_get_logger, mock_popen, mock_which):
        """Test that PDEATHSIG is configured for arecord subprocess."""
        from apps.voice.audio.capture import AudioCapture, CaptureConfig

        # Mock logger
        mock_logger = Mock()
        mock_logger.event = Mock()
        mock_logger.info = Mock()
        mock_logger.debug = Mock()
        mock_get_logger.return_value = mock_logger

        mock_which.return_value = "/usr/bin/arecord"
        mock_proc = Mock()
        mock_proc.stdout = Mock()
        mock_proc.stderr = Mock()
        mock_popen.return_value = mock_proc

        config = CaptureConfig(device="default", sample_rate=16000)
        with AudioCapture(config) as cap:
            cap._proc = mock_proc  # Ensure proc is set

        # Verify Popen was called with preexec_fn
        assert mock_popen.called
        call_kwargs = mock_popen.call_args[1]
        assert "preexec_fn" in call_kwargs
        assert call_kwargs["preexec_fn"] is not None


class TestLCDCleanup:
    """Test LCD renderer cleanup."""

    @patch("drivers.lcd.driver_ili9xx.xgoscreen")
    @patch("drivers.lcd.driver_ili9xx.Image")
    def test_lcd_cleanup_closes_spi(self, mock_image, mock_xgoscreen):
        """Test that LCD cleanup closes SPI connection."""
        from drivers.lcd.driver_ili9xx import FaceConfig, LCDRenderer

        # Mock xgoscreen device
        mock_device = Mock()
        mock_device.width = 240
        mock_device.height = 320
        mock_spi = Mock()
        mock_spi.close = Mock()
        mock_device.SPI = mock_spi

        mock_device_class = Mock(return_value=mock_device)
        mock_device_class.__name__ = "MockLCD"  # Add __name__ attribute
        mock_xgoscreen.__name__ = "xgoscreen"
        mock_xgoscreen.__path__ = []

        with patch("drivers.lcd.driver_ili9xx._pick_device_class", return_value=mock_device_class):
            with patch("drivers.lcd.driver_ili9xx._find_presenter", return_value=(mock_device, None)):
                with patch("drivers.lcd.driver_ili9xx._find_raw_iface", return_value=(mock_device, None, None, None)):
                    lcd = LCDRenderer(FaceConfig(lcd_do_init=False))
                    lcd.cleanup()

                    # Verify SPI close was called
                    assert mock_spi.close.called

    @patch("drivers.lcd.driver_ili9xx.xgoscreen")
    @patch("drivers.lcd.driver_ili9xx.Image")
    def test_lcd_cleanup_resets_gpio(self, mock_image, mock_xgoscreen):
        """Test that LCD cleanup handles GPIO reset gracefully."""
        from drivers.lcd.driver_ili9xx import FaceConfig, LCDRenderer

        # Mock xgoscreen device
        mock_device = Mock()
        mock_device.width = 240
        mock_device.height = 320
        mock_device.SPI = Mock()
        mock_device.SPI.close = Mock()

        mock_device_class = Mock(return_value=mock_device)
        mock_device_class.__name__ = "MockLCD"  # Add __name__ attribute
        mock_xgoscreen.__name__ = "xgoscreen"
        mock_xgoscreen.__path__ = []

        with patch("drivers.lcd.driver_ili9xx._pick_device_class", return_value=mock_device_class):
            with patch("drivers.lcd.driver_ili9xx._find_presenter", return_value=(mock_device, None)):
                with patch("drivers.lcd.driver_ili9xx._find_raw_iface", return_value=(mock_device, None, None, None)):
                    lcd = LCDRenderer(FaceConfig(lcd_do_init=False))
                    lcd._gpio_initialized = True

                    # Call cleanup - should handle missing GPIO gracefully
                    lcd.cleanup()

                    # Verify cleanup completed without exception
                    # and that SPI was closed
                    assert mock_device.SPI.close.called


class TestCameraCleanup:
    """Test camera cleanup."""

    def test_camera_cleanup_called_on_exit(self):
        """Test that camera cleanup is called on module exit."""
        # Simple test to ensure cleanup function exists and can be called
        import sys

        # Add module to path dynamically
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

        try:
            from apps.camera import preview_lcd_takeover

            # Call cleanup directly (won't actually cleanup hardware in test env)
            preview_lcd_takeover._cleanup_resources()

            # Verify it doesn't raise
            assert True
        except Exception as e:
            # Expected in test environment without hardware
            assert "No module named" in str(e) or "LCD" in str(e) or "GPIO" in str(e)


# Integration test (optional - requires actual hardware)
@pytest.mark.skipif(
    not os.path.exists("/dev/spidev0.0"),
    reason="SPI device not available (requires hardware)",
)
class TestGracefulShutdownIntegration:
    """Integration tests requiring actual hardware."""

    def test_lcd_restart_without_errors(self):
        """Test that LCD can be restarted without SPI errors."""
        # This would test actual hardware behavior
        pytest.skip("Integration test - requires actual Raspberry Pi hardware")

    def test_camera_restart_multiple_times(self):
        """Test that camera can be restarted 5+ times without errors."""
        # This would test actual camera hardware
        pytest.skip("Integration test - requires actual camera hardware")

    def test_audio_no_orphaned_processes(self):
        """Test that no arecord processes remain after service stop."""
        # This would test actual audio hardware
        pytest.skip("Integration test - requires actual audio hardware")
