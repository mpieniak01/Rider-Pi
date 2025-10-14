# Systemd Services → Scripts Mapping

This document provides a mapping of all systemd service files to the scripts they execute after the migration to `scripts/`.

## Service Files Status

| Service File | Status | ExecStart Path | Notes |
|--------------|--------|----------------|-------|
| **jupyter.service** | ✓ Valid | `/usr/bin/python3 -m jupyter lab` | System Python module |
| **rider-api.service** | ✓ Valid | `/usr/bin/python3 -u -m services.api_server` | Python module in `services/` |
| **rider-boot-prepare.service** | ✓ Valid | `/home/pi/robot/scripts/sys_boot-prepare.sh` | Script in `scripts/` |
| **rider-broker.service** | ✓ Valid | `/usr/bin/python3 -u services/broker.py` | Python script in `services/` |
| **rider-cam-preview.service** | ✓ Valid | `/usr/bin/python3 apps/camera/preview_lcd.py` | Python script in `apps/` |
| **rider-edge-preview.service** | ✓ Valid | `/usr/bin/python3 -u apps/vision/edge_preview.py` | Python script in `apps/` |
| **rider-face.service** | ✓ Fixed | `/usr/bin/python3 /home/pi/robot/scripts/dev_face-lcd-direct.py` | **Updated from** `/workspaces/Rider-Pi/tools/` |
| **rider-motion-bridge.service** | ✓ Valid | `/usr/bin/python3 -u -m services.motion_bridge` | Python module in `services/` |
| **rider-obstacle.service** | ✓ Valid | `/usr/bin/python3 -u apps/vision/obstacle_roi.py` | Python script in `apps/` |
| **rider-post-splash.service** | ✓ Fixed | `/usr/bin/python3 scripts/sys_splash-info.py` | **Updated from** `ops/splash_device_info.py` |
| **rider-ssd-preview.service** | ✓ Valid | `/usr/bin/python3 -u apps/camera/preview_lcd_ssd.py` | Python script in `apps/` |
| **rider-vision.service** | ✓ Valid | `/usr/bin/python3 -u apps/vision/dispatcher.py` | Python script in `apps/` |
| **rider-voice-web.service** | ✓ Valid | `/usr/bin/python3 -m apps.voice.web` | Python module in `apps/` |
| **rider-voice.service** | ✓ Valid | `/usr/bin/python3 -m apps.voice.cli listen` | Python module in `apps/` |
| **rider-web-bridge.service** | ✓ Valid | `/usr/bin/python3 -u -m services.web_motion_bridge` | Python module in `services/` |
| **wifi-unblock.service** | ✓ Valid | `/usr/sbin/rfkill unblock wifi` | System command |

## Changes Made in This PR

### Fixed Service Files

#### 1. rider-face.service
**Before:**
```ini
ExecStart=/usr/bin/python3 /workspaces/Rider-Pi/tools/newface_lcd_direct.py --expr neutral ...
EnvironmentFile=/workspaces/Rider-Pi/systemd/robot.env
```

**After:**
```ini
WorkingDirectory=/home/pi/robot
EnvironmentFile=-/home/pi/robot/systemd/robot.env
Environment=PYTHONPATH=/home/pi/robot
ExecStart=/usr/bin/python3 /home/pi/robot/scripts/dev_face-lcd-direct.py --expr neutral ...
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
```

**Changes:**
- ✓ Updated path from `/workspaces/Rider-Pi/tools/` to `/home/pi/robot/scripts/`
- ✓ Fixed script name: `newface_lcd_direct.py` → `dev_face-lcd-direct.py`
- ✓ Updated EnvironmentFile path
- ✓ Added WorkingDirectory
- ✓ Added PYTHONPATH environment variable
- ✓ Added RestartSec
- ✓ Added StandardOutput/StandardError for consistent logging

#### 2. rider-post-splash.service
**Before:**
```ini
ConditionPathExists=/home/pi/robot/ops/splash_device_info.py
ExecStart=/usr/bin/env bash -lc 'SPLASH_WAIT_IP_S=60 /usr/bin/python3 ops/splash_device_info.py'
```

**After:**
```ini
ConditionPathExists=/home/pi/robot/scripts/sys_splash-info.py
ExecStart=/usr/bin/env bash -lc 'SPLASH_WAIT_IP_S=60 /usr/bin/python3 scripts/sys_splash-info.py'
```

**Changes:**
- ✓ Updated ConditionPathExists from `ops/` to `scripts/`
- ✓ Updated ExecStart path from `ops/` to `scripts/`
- ✓ Updated script name: `splash_device_info.py` → `sys_splash-info.py`

## Script Migration Reference

Based on `docs/_pr_summaries/SCRIPTS_MIGRATION_SUMMARY.md`:

| Old Path | New Path | Category |
|----------|----------|----------|
| `ops/splash_device_info.py` | `scripts/sys_splash-info.py` | System operation |
| `tools/newface_lcd_direct.py` | `scripts/dev_face-lcd-direct.py` | Development tool |

## Validation

All service files have been validated with:

1. **systemd-analyze verify** - Syntax validation
2. **Path validation** - All referenced files exist
3. **Pattern check** - No deprecated paths (`/workspaces/`, `ops/`, `tools/`)
4. **Consistency check** - Proper WorkingDirectory settings

Run validation:
```bash
./scripts/diag_systemd-smoke.sh
```

## Service File Standards

After this PR, all service files follow these standards:

1. **WorkingDirectory**: Set to `/home/pi/robot` for Python scripts that import project modules
2. **PYTHONPATH**: Explicitly set to `/home/pi/robot` when needed
3. **Restart policies**: `on-failure` with `RestartSec=5` (or 3) for consistency
4. **Logging**: `StandardOutput=journal` and `StandardError=journal` where applicable
5. **Paths**: All paths use either:
   - Absolute system paths: `/usr/bin/python3`
   - Relative to WorkingDirectory: `apps/camera/preview_lcd.py`
   - Absolute project paths: `/home/pi/robot/scripts/sys_boot-prepare.sh`

## Testing

The following commands can be used to test service file validity:

```bash
# Validate all service files
./scripts/diag_validate-systemd-paths.py

# Run comprehensive smoke tests
./scripts/diag_systemd-smoke.sh

# Verify specific service file
systemd-analyze verify systemd/rider-face.service

# Test service on actual system
sudo systemctl daemon-reload
sudo systemctl start rider-face.service
sudo systemctl status rider-face.service
```

## CI Integration

Service file validation is now part of the CI pipeline in `.github/workflows/quality-guard.yml`:

```yaml
- name: Validate systemd service files
  run: bash scripts/diag_systemd-smoke.sh
```

This ensures that any PR that modifies service files or referenced scripts will be validated automatically.

---

**Last updated:** 2025-10-14  
**Related PR:** Fix systemd services after file renames/move to `scripts/`
