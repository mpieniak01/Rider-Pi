# Scripts Directory

This directory contains all operational, diagnostic, development, and utility scripts for the Rider-Pi project. Previously split between `ops/` and `tools/`, all scripts are now consolidated here with a unified naming convention.

## Naming Convention

All scripts follow the pattern: **`[category]_[functional-description]`**

### Categories

#### `sys_` - System Operations
Scripts for system management, services, boot, and critical operations:
- `sys_control.sh` - Service control
- `sys_systemd-sync.sh` - Systemd synchronization
- `sys_boot-prepare.sh` - Boot preparation
- `sys_cleanup.sh` - Services cleanup
- `sys_camera-preview.sh` - Camera preview
- `sys_camera-kill.sh` - Kill camera takeover
- `sys_kill-cam.sh` - Kill camera processes
- `sys_vision-control.sh` - Vision control
- `sys_lcd-control.py` - LCD control
- `sys_led-control.py` - LED control
- `sys_emergency-stop.py` - Emergency stop
- `sys_xgo-init.py` - XGO safe initialization
- `sys_splash-info.py` - Splash screen with device info
- `sys_splash-info.sh` - Splash screen wrapper
- `sys_vendor-splash.py` - Vendor splash screen
- `sys_voice-once.sh` - Voice single interaction
- `sys_voice-run.sh` - Voice continuous run
- `sys_voice-stream.sh` - Voice streaming

#### `diag_` - Diagnostics and Monitoring
Scripts for diagnostics, monitoring, and testing:
- `diag_bench-detect.sh` - Detection benchmark
- `diag_test-suite.sh` - Test suite
- `diag_tests-audit.sh` - Tests audit
- `diag_sensors.py` - Check XGO sensors
- `diag_metrics.sh` - Monitor metrics
- `diag_stream.sh` - Monitor streams
- `diag_framebuffer-grab.py` - Framebuffer capture
- `diag_xgo-bootloader.py` - XGO bootloader probe
- `diag_bus-spy.py` - Message bus spy
- `diag_lcd-raw.py` - LCD raw diagnostics
- `diag_websocket-probe.py` - WebSocket probe

#### `dev_` - Development Tools
Scripts for development, manual control, and testing:
- `dev_manual-drive.py` - Manual robot control
- `dev_check-file-length.py` - Check file length
- `dev_check-legacy-imports.py` - Check for legacy imports
- `dev_face-cli.py` - Face API CLI
- `dev_face-lcd-clean.py` - Face LCD cleanup
- `dev_face-presenter.py` - Face presenter only
- `dev_face-lcd-direct.py` - Direct LCD face rendering
- `dev_lcd-clear.py` - LCD clear/presenter
- `dev_lcd-testcard.py` - LCD test card
- `dev_lcd-show-raw.py` - LCD raw display
- `dev_panel-nuke.py` - Panel nuke and bars
- `dev_panel-reset.py` - Panel reset
- `dev_panel-reset-safe.py` - Safe panel reset
- `dev_bus-pub.py` - Bus publisher
- `dev_bus-sub.py` - Bus subscriber
- `dev_bus-dump.py` - Bus dump
- `dev_bus-state.py` - Bus state
- `dev_send-cmd.py` - Send command
- `dev_keyboard-sim.py` - Keyboard simulator
- `dev_xgo-client.py` - XGO client (read-only)

#### `demo_` - Demos
Demo scripts showcasing functionality:
- `demo_trajectory.py` - Trajectory demo (lemniscate)
- `demo_weather-lcd.py` - Weather LCD demo

#### `util_` - Utilities
Helper scripts and utilities:
- `util_export-env.sh` - Export environment variables
- `util_volume-hooks.sh` - Volume hooks
- `util_load-config.sh` - Load configuration helper
- `util_volume.py` - Volume control

## Quick Reference

### Common Operations

**System Control:**
```bash
./scripts/sys_control.sh <service> <action>
./scripts/sys_emergency-stop.py on|off|status
```

**Diagnostics:**
```bash
./scripts/diag_sensors.py          # Check XGO sensors
./scripts/diag_bus-spy.py          # Monitor message bus
./scripts/diag_test-suite.sh       # Run test suite
```

**Development:**
```bash
./scripts/dev_manual-drive.py      # Manual robot control
./scripts/dev_bus-pub.py <topic> <data>
./scripts/dev_bus-sub.py <topic>
```

**LCD/Display:**
```bash
sudo python3 scripts/sys_lcd-control.py on|off|status
./scripts/dev_face-lcd-direct.py --expr neutral --secs 5
./scripts/dev_lcd-clear.py
```

**Voice:**
```bash
./scripts/sys_voice-once.sh        # Single interaction
./scripts/sys_voice-run.sh         # Continuous run
```

## Migration Notes

This directory consolidates scripts from the previous `ops/` and `tools/` directories:

- **ops/** → All operational scripts moved to `scripts/` with `sys_`, `diag_`, or `util_` prefix
- **tools/** → All development tools moved to `scripts/` with `dev_`, `diag_`, or `util_` prefix
- **Preserved:** `ops/agent/` and `ops/audio/` subdirectories remain in place

For detailed migration mapping, see `SCRIPTS_MIGRATION_SUMMARY.md` in the project root.

## Usage from Makefile

Many scripts are integrated into the Makefile for convenience:

```bash
make bus-spy           # Run diag_bus-spy.py
make lcd-on            # Run sys_lcd-control.py on
make lcd-off           # Run sys_lcd-control.py off
```

See `Makefile` for all available targets.

## Best Practices

1. **Use absolute paths** or detect repo root when referencing other files
2. **Log to stderr** for informational messages, stdout for data
3. **Use `set -euo pipefail`** in bash scripts for fail-fast behavior
4. **Make scripts idempotent** when possible
5. **Include usage information** in script headers or via `--help`

## Related Documentation

- `docs/ops/` - Detailed documentation for operational scripts
- `SCRIPTS_MIGRATION_SUMMARY.md` - Complete migration details
- `Makefile` - Integration with build system

## Contributing

When adding new scripts:
1. Follow the naming convention: `[category]_[functional-description]`
2. Choose the appropriate category prefix
3. Make the script executable: `chmod +x scripts/your_script`
4. Add documentation to this README
5. Update Makefile if the script should have a make target

---

**Last Updated:** 2025-10 (PR #13 - ops/tools consolidation)
