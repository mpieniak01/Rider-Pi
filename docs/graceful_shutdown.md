# Graceful Shutdown - Usage Guide

## Overview

The graceful shutdown mechanism ensures proper cleanup of hardware resources (LCD, Audio, Camera) when services are stopped or restarted. This eliminates the need for external kill scripts and prevents resource leaks.

## Components

### 1. GracefulShutdown Handler (`common/graceful_shutdown.py`)

A reusable signal handler for SIGTERM and SIGINT:

```python
from common.graceful_shutdown import GracefulShutdown

shutdown = GracefulShutdown()

# Register cleanup handlers
shutdown.register_cleanup(lambda: print("Cleaning up..."))
shutdown.register_cleanup(cleanup_resources)

# Use as context manager
with shutdown:
    while not shutdown.should_stop:
        # Main application loop
        do_work()
```

### 2. LCD Cleanup (`drivers/lcd/driver_ili9xx.py`)

LCD driver now includes automatic cleanup:

```python
from drivers.lcd.driver_ili9xx import LCDRenderer, FaceConfig

lcd = LCDRenderer(FaceConfig())
# ... use lcd ...

# Cleanup is automatic via destructor (__del__)
# Or call manually:
lcd.cleanup()  # Closes SPI, resets GPIO
```

**What it does:**
- Closes SPI connection
- Turns off backlight (BL pin)
- Resets DC and RST pins to INPUT mode
- Calls GPIO.cleanup()

### 3. Audio Subprocess Cleanup (`apps/voice/audio/capture.py`)

AudioCapture now uses PDEATHSIG to prevent orphaned processes:

```python
from apps.voice.audio.capture import AudioCapture, CaptureConfig

config = CaptureConfig(device="default", sample_rate=16000)
with AudioCapture(config) as cap:
    for frame in cap.frames():
        process_audio(frame)
# arecord subprocess is automatically terminated on exit
```

**What it does:**
- Sets PR_SET_PDEATHSIG to SIGKILL for arecord subprocess
- Kernel automatically kills arecord when Python process dies
- No orphaned audio processes

### 4. PID Lock Cleanup (`common/pidlock.py`)

PID locks are now automatically cleaned up:

```python
from common.pidlock import single_instance

# Lock file is automatically removed on normal exit
fd = single_instance("/tmp/my-service.lock")
# ... run service ...
# Lock file cleaned up via atexit
```

### 5. Camera Cleanup (`apps/camera/__main__.py`)

Camera resources are cleaned up on exit:

```python
# apps/camera/__main__.py wraps preview_main() in try/finally
# Automatically calls cv2.destroyAllWindows() on exit
```

## Testing

Run the test suite to verify graceful shutdown behavior:

```bash
python3 -m pytest tests/test_graceful_shutdown.py -v
```

**Test coverage:**
- Signal handler registration and execution
- PID lock file cleanup
- Audio subprocess termination
- PDEATHSIG configuration
- LCD SPI/GPIO cleanup
- Camera resource cleanup

## Systemd Integration

Services using systemd benefit automatically:

```ini
[Unit]
Description=Rider Camera Service

[Service]
Type=simple
ExecStart=/usr/bin/python3 -m apps.camera
Restart=on-failure
# SIGTERM is sent on stop - cleanup handlers will run
KillMode=mixed
TimeoutStopSec=5

[Install]
WantedBy=multi-user.target
```

**Service commands:**
```bash
# Stop service - triggers graceful shutdown
sudo systemctl stop rider-camera

# Restart service - cleanup runs before restart
sudo systemctl restart rider-camera
```

## Verification

### Check for Orphaned Processes

**Before (with external kill scripts):**
```bash
# arecord processes left running after service stop
ps aux | grep arecord
```

**After (with graceful shutdown):**
```bash
# No orphaned processes
ps aux | grep arecord  # Should return nothing
```

### Check PID Lock Files

```bash
# Lock files cleaned up automatically
ls /tmp/*.lock  # Should not show stale locks
```

### Check SPI/GPIO State

```bash
# SPI and GPIO properly released
lsof | grep spidev  # Should not show locks after service stop
```

## Troubleshooting

### Service Won't Stop

If service hangs on stop:
1. Check `TimeoutStopSec` in systemd unit file
2. Increase if cleanup takes longer
3. Check logs: `journalctl -u rider-camera -n 50`

### Resources Still Locked

If resources remain locked after stop:
1. Verify cleanup handlers are registered
2. Check for exceptions in cleanup code
3. Use `sudo lsof /dev/spidev*` to identify processes
4. Restart as last resort: `sudo systemctl restart rider-camera`

### Tests Failing

Integration tests require hardware:
```bash
# Skip hardware tests
pytest tests/test_graceful_shutdown.py -v -m "not integration"

# Run with hardware
pytest tests/test_graceful_shutdown.py -v
```

## Migration from Kill Scripts

### Before (with kill scripts)

```bash
# scripts/sys_camera-kill.sh
pkill -f 'apps/camera/preview_lcd_takeover.py'
pkill -f 'arecord'
fuser -k /dev/spidev0.0
fuser -k /dev/video0
```

### After (with graceful shutdown)

```bash
# Simply stop the service - cleanup is automatic
sudo systemctl stop rider-camera
sudo systemctl stop rider-voice
```

**Kill scripts are no longer required** and can be deprecated or removed.

## Best Practices

1. **Always use context managers** for resources (AudioCapture, etc.)
2. **Register cleanup handlers** early in service initialization
3. **Test cleanup** by stopping/restarting services
4. **Monitor logs** for cleanup errors during development
5. **Use systemd** for service management (better than manual scripts)

## Related Files

- `common/graceful_shutdown.py` - Signal handler utility
- `common/pidlock.py` - PID lock with cleanup
- `apps/voice/audio/capture.py` - Audio with PDEATHSIG
- `drivers/lcd/driver_ili9xx.py` - LCD with cleanup
- `apps/camera/__main__.py` - Camera cleanup wrapper
- `apps/camera/preview_lcd_takeover.py` - Camera with atexit
- `tests/test_graceful_shutdown.py` - Test suite
