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
| **rider-choreographer.service** | ✓ Valid | `/usr/bin/python3 -u -m apps.choreographer.main` | Emotion and sentiment choreography service |
| **rider-edge-preview.service** | ✓ Valid | `/usr/bin/python3 -u apps/vision/edge_preview.py` | Python script in `apps/` |
| **rider-face.service** | ✓ Fixed | `/usr/bin/python3 /home/pi/robot/scripts/dev_face-lcd-direct.py` | **Updated from** `/workspaces/Rider-Pi/tools/` |
| **rider-google-bridge.service** | ✓ Valid | `/usr/bin/python3 -u -m apps.google_bridge.main` | Python module in `apps/` |
| **rider-mapper.service** | ✓ Valid | `/usr/bin/python3 /home/pi/robot/apps/mapper/main.py` | **Rekonesans Stage 3**: SLAM mapping service |
| **rider-motion-bridge.service** | ✓ Valid | `/usr/bin/python3 -u -m services.motion_bridge` | Python module in `services/` |
| **rider-obstacle.service** | ✓ Valid | `/usr/bin/python3 -u apps/vision/obstacle_roi.py` | Python script in `apps/` |
| **rider-odometry.service** | ✓ Valid | `/usr/bin/python3 -u -m apps.odometry.main` | **Rekonesans Stage 2**: Position tracking service |
| **rider-tracker.service** | ✓ Valid | `/usr/bin/python3 -u apps/vision/tracker.py` | Vision tracking service |
| **rider-tracking-controller.service** | ✓ Valid | `/usr/bin/python3 -u apps/motion/tracking_controller.py` | Motion tracking controller |
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

### Static Tests (No systemd required)

```bash
# Python validator - checks paths exist
./scripts/diag_validate-systemd-paths.py

# Comprehensive bash smoke tests
./scripts/diag_systemd-smoke.sh

# Pytest-based static tests
pytest tests/test_systemd_services.py -v
```

### Smoke Tests (Requires systemd)

```bash
# Enable systemd smoke tests (checks systemd-analyze verify)
SYSTEMD_SMOKE_TESTS=1 pytest tests/test_systemd_smoke.py -v

# Full smoke tests (includes service start/stop - requires root)
SYSTEMD_SMOKE_TESTS=1 SYSTEMD_SMOKE_FULL=1 pytest tests/test_systemd_smoke.py -v
```

### Manual Verification

```bash
# Verify specific service file syntax
systemd-analyze verify systemd/rider-face.service

# Test service on actual system
sudo systemctl daemon-reload
sudo systemctl start rider-face.service
sudo systemctl status rider-face.service
```

### Local Testing Instructions

1. **Quick validation** (no dependencies):
   ```bash
   bash scripts/diag_systemd-smoke.sh
   ```

2. **Full pytest suite** (requires pytest):
   ```bash
   pip install pytest pytest-timeout
   pytest tests/test_systemd_services.py -v
   ```

3. **With systemd** (on robot or systemd-enabled system):
   ```bash
   SYSTEMD_SMOKE_TESTS=1 pytest tests/test_systemd_smoke.py -v
   ```

## CI Integration

Service file validation is now part of the CI pipeline:

### quality-guard.yml (Always runs)

```yaml
- name: Validate systemd service files (bash smoke test)
  run: bash scripts/diag_systemd-smoke.sh

- name: Validate systemd service files (pytest static tests)
  run: pytest tests/test_systemd_services.py -v
```

**Tests performed:**
- ✅ systemd-analyze verify (syntax validation)
- ✅ Path validation (all ExecStart paths exist)
- ✅ Deprecated pattern detection (no ops/, tools/, /workspaces/)
- ✅ Consistency checks (WorkingDirectory for Python services)
- ✅ Description field presence and non-empty
- ✅ No duplicate ExecStart → missing file errors

### tests.yml (Conditional)

```yaml
systemd-smoke:
  if: contains(github.event.pull_request.labels.*.name, 'test-systemd')
  ...
  - name: Run systemd smoke tests
    env:
      SYSTEMD_SMOKE_TESTS: "1"
    run: pytest tests/test_systemd_smoke.py -v
```

**Trigger:** Add `test-systemd` label to PR

**Tests performed:**
- ✅ systemd-analyze verify on actual systemd
- ✅ Service file loading verification
- ✅ daemon-reload succeeds

**Note:** Full service start/stop tests require `SYSTEMD_SMOKE_FULL=1` and root privileges.

### Test Failure Handling

Any PR that modifies service files or referenced scripts will be validated automatically:

- ❌ **Block merge** if ExecStart references non-existent files
- ❌ **Block merge** if deprecated paths are detected
- ❌ **Block merge** if Description field is missing or empty
- ⚠️ **Warning only** for missing WorkingDirectory (some services may not need it)

This ensures that any PR that modifies service files or referenced scripts will be validated automatically.

## Notes on Rekonesans (Autonomous Navigation) Services

### Navigator Service
**Note:** There is currently **no dedicated `rider-navigator.service`**. The navigator module (`apps/navigator/main.py`) is designed to be controlled via the API (`/api/navigator/*` endpoints) and does not run as a persistent background service. It can be started on-demand through the web interface or API calls.

If a persistent navigator service is needed, it can be created similar to the odometry and mapper services.

### Service Dependencies (Rekonesans Epic)
The autonomous navigation (Rekonesans) feature spans multiple services:

1. **rider-odometry.service** (Stage 2) - Position tracking
   - Depends on: `rider-broker.service`, `rider-motion-bridge.service`
   - Publishes: `robot.pose` (position and orientation)

2. **rider-mapper.service** (Stage 3) - SLAM mapping
   - Depends on: `rider-broker.service`, `rider-odometry.service`
   - Subscribes: `robot.pose`, `vision.obstacle.data`
   - Publishes: `mapper.map.data` (occupancy grid)

3. **Navigator** (Stages 1 & 4) - Exploration and path planning
   - Controlled via API: `/api/navigator/*`
   - Subscribes: `vision.obstacle`, `robot.pose`, `mapper.map.data`
   - Publishes: `navigator.state`, `motion` commands

### Vision Depth Bridge
The `apps/vision/depth_bridge.py` module provides obstacle distance estimation for mapping. It does not have a dedicated systemd service but can be integrated into the vision pipeline as needed.

---

**Last updated:** 2025-10-14  
**Related PR:** Fix systemd services after file renames/move to `scripts/`
