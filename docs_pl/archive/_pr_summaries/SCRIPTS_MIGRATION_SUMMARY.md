# Scripts Migration Summary (PR #13)

## Overview
Consolidated and reorganized scripts from `ops/` and `tools/` directories into a single, flat `scripts/` directory with unified naming convention.

## Naming Convention
All scripts now follow the pattern: `[category]_[functional-description]`

### Categories:
- **sys_** - System operations, services, boot
- **diag_** - Diagnostics and monitoring
- **dev_** - Development tools, manual control
- **demo_** - Demo scripts
- **util_** - Utilities and helpers

## File Migrations

### From ops/ (31 files migrated):

#### System Operations (sys_)
| Old Path | New Path |
|----------|----------|
| ops/service_ctl.sh | scripts/sys_control.sh |
| ops/systemd_sync.sh | scripts/sys_systemd-sync.sh |
| ops/boot_prepare.sh | scripts/sys_boot-prepare.sh |
| ops/services_cleanup.sh | scripts/sys_cleanup.sh |
| ops/camera_preview.sh | scripts/sys_camera-preview.sh |
| ops/camera_takeover_kill.sh | scripts/sys_camera-kill.sh |
| ops/kill_cam.sh | scripts/sys_kill-cam.sh |
| ops/vision_ctl.sh | scripts/sys_vision-control.sh |
| ops/lcdctl.py | scripts/sys_lcd-control.py |
| ops/ledctl.py | scripts/sys_led-control.py |
| ops/estop.py | scripts/sys_emergency-stop.py |
| ops/xgo_safe_init.py | scripts/sys_xgo-init.py |
| ops/splash_device_info.py | scripts/sys_splash-info.py |
| ops/splash_device_info.sh | scripts/sys_splash-info.sh |
| ops/vendor_splash.py | scripts/sys_vendor-splash.py |
| ops/voice-once.sh | scripts/sys_voice-once.sh |
| ops/voice-run.sh | scripts/sys_voice-run.sh |
| ops/voice_stream_chat.sh | scripts/sys_voice-stream.sh |

#### Diagnostics (diag_)
| Old Path | New Path |
|----------|----------|
| ops/bench_detect.sh | scripts/diag_bench-detect.sh |
| ops/test_suite.sh | scripts/diag_test-suite.sh |
| ops/tests_audit.sh | scripts/diag_tests-audit.sh |
| ops/check_xgo_sensors.py | scripts/diag_sensors.py |
| ops/monitor_metrics.sh | scripts/diag_metrics.sh |
| ops/monitor_stream.sh | scripts/diag_stream.sh |
| ops/fbgrab.py | scripts/diag_framebuffer-grab.py |
| ops/xgo_bl_probe.py | scripts/diag_xgo-bootloader.py |

#### Demo
| Old Path | New Path |
|----------|----------|
| ops/demo_lemniscate.py | scripts/demo_trajectory.py |

#### Utilities (util_)
| Old Path | New Path |
|----------|----------|
| ops/export_env.sh | scripts/util_export-env.sh |
| ops/volume_hooks.sh | scripts/util_volume-hooks.sh |

### From tools/ (27 files migrated):

#### Utilities (util_)
| Old Path | New Path |
|----------|----------|
| tools/load_config.sh | scripts/util_load-config.sh |
| tools/volume.py | scripts/util_volume.py |

#### Development Tools (dev_)
| Old Path | New Path |
|----------|----------|
| tools/manual_drive.py | scripts/dev_manual-drive.py |
| tools/check_file_length.py | scripts/dev_check-file-length.py |
| tools/check_legacy_imports.py | scripts/dev_check-legacy-imports.py |
| tools/face_cli.py | scripts/dev_face-cli.py |
| tools/face_lcd_clean.py | scripts/dev_face-lcd-clean.py |
| tools/face_presenter_only.py | scripts/dev_face-presenter.py |
| tools/newface_lcd_direct.py | scripts/dev_face-lcd-direct.py |
| tools/lcd_presenter_clear.py | scripts/dev_lcd-clear.py |
| tools/lcd_presenter_testcard.py | scripts/dev_lcd-testcard.py |
| tools/lcd_show_raw.py | scripts/dev_lcd-show-raw.py |
| tools/panel_nuke_and_bars.py | scripts/dev_panel-nuke.py |
| tools/panel_reset.py | scripts/dev_panel-reset.py |
| tools/panel_reset_safe.py | scripts/dev_panel-reset-safe.py |
| tools/pub.py | scripts/dev_bus-pub.py |
| tools/sub.py | scripts/dev_bus-sub.py |
| tools/sub_dump.py | scripts/dev_bus-dump.py |
| tools/sub_state.py | scripts/dev_bus-state.py |
| tools/send_cmd.py | scripts/dev_send-cmd.py |
| tools/sim_keyboard_control.py | scripts/dev_keyboard-sim.py |
| tools/xgo_client_ro.py | scripts/dev_xgo-client.py |

#### Diagnostics (diag_)
| Old Path | New Path |
|----------|----------|
| tools/bus_spy.py | scripts/diag_bus-spy.py |
| tools/lcd_diag_raw.py | scripts/diag_lcd-raw.py |
| tools/ws_probe.py | scripts/diag_websocket-probe.py |

#### Demo
| Old Path | New Path |
|----------|----------|
| tools/weather_lcd.py | scripts/demo_weather-lcd.py |

## Special Cases Handled

### Deleted Files
- **tools/lcdctl.py** - Removed (was a stub file, real implementation moved from ops/lcdctl.py)

### Preserved Subdirectories
- **ops/agent/** - Kept in place (contains agent-specific files)
- **ops/audio/** - Kept in place (contains audio-specific files)

## Updated References

### Code Files (10 files)
- apps/camera/preview_lcd.py
- apps/nlu/main.py
- apps/ui/face/controller.py
- apps/ui/volume_hooks.sh
- demo_simulator.sh
- robot_dev.sh
- run_boot.sh
- services/_deprecated_20250918_145436/services_api-checkpoint.py
- services/api_core/services_api.py
- services/broker.py

### Test Files (4 files)
- tests/test_face_raw_fastpath.py
- tests/test_no_underscore_apps_dependency.py
- tests/test_simulator_integration.py
- tests/verify_simulator.py
- examples/demo_sim3_sensors.py

### Configuration Files (5 files)
- .pre-commit-config.yaml
- Makefile
- AGENT.md
- ARCHITECTURE.md
- ARCHITECTURE_REFACTORING.md
- WORKING-AGREEMENTS.md

### Documentation Files (29+ files)
- All files in docs/ops/
- All files in docs/modules/
- All files in docs/config/
- All files in docs/apps/
- All files in docs/release-notes/
- All files in docs/summaries/
- Multiple PR summary files (PR2_SUMMARY.md, PR4_SUMMARY.md, PR10_SUMMARY.md, etc.)

### Internal Script References
All scripts in the new `scripts/` directory had their internal references updated to use the new paths.

## Statistics

- **Total files migrated**: 58 files
- **Files deleted**: 1 file (stub)
- **Files with updated references**: 49+ files across the codebase
- **New directory structure**: Flat hierarchy in `scripts/`
- **Naming patterns applied**: 5 categories (sys_, diag_, dev_, demo_, util_)

## Verification Checklist

- [x] All files from ops/ (except agent/ and audio/ subdirs) moved to scripts/
- [x] All files from tools/ moved to scripts/
- [x] New naming convention applied to all files
- [x] All code references updated
- [x] All test references updated
- [x] All documentation references updated
- [x] Makefile updated
- [x] CI/CD configuration updated (.pre-commit-config.yaml)
- [x] Internal script references updated
- [x] No broken references to old paths (verified with grep)

## Impact

This reorganization:
1. **Simplifies navigation** - All scripts in one location with clear naming
2. **Improves discoverability** - Category prefixes make it easy to find scripts by purpose
3. **Reduces confusion** - Eliminates overlap between ops/ and tools/
4. **Maintains history** - All moves done with `git mv` to preserve file history
5. **Preserves functionality** - All internal and external references updated

## Next Steps

After this PR is merged:
1. Update any local scripts or workflows that reference old paths
2. Consider creating a README.md in scripts/ directory explaining the categories
3. Consider adding a migration guide for developers with local forks
