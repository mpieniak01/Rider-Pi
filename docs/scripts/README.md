# `scripts` Directory

This directory contains all operational, diagnostic, development, and utility scripts for the **Rider-Pi** project.  
Previously, scripts were divided between the `ops/` and `tools/` directories, but they have now been **consolidated** into one location with a unified naming scheme.

## Naming Convention

All scripts follow the pattern:  
**`[category]_[functional-description]`**

### Categories

#### `sys_` – System Operations  
Scripts for managing the system, services, startup, and critical operations

#### `diag_` – Diagnostics and Monitoring  
Scripts for tests, monitoring, and diagnostics

#### `dev_` – Development Tools  
Scripts for development, manual control, and testing

#### `demo_` – Demos  
Demonstration scripts showcasing system features

#### `util_` – Utility Tools  
Supporting and utility scripts

#### `talk_` – Interactive Voice Demos
Demonstration scripts for local TTS/ASR (Piper/Vosk)

> **Requires:** running `rider-voice-web.service` on port 8092

---

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
./scripts/diag_bus-spy.py          # Inspect message bus
./scripts/diag_test-suite.sh       # Run test suite
```

**Development:**
```bash
./scripts/dev_manual-drive.py      # Manual robot control
./scripts/dev_bus-pub.py <topic> <data>
./scripts/dev_bus-sub.py <topic>
```

**LCD / Display:**
```bash
sudo python3 scripts/sys_lcd-control.py on|off|status
./scripts/dev_face-lcd-direct.py --expr neutral --secs 5
./scripts/dev_lcd-clear.py
```

**Voice:**
```bash
./scripts/sys_voice-once.sh        # Single voice interaction
./scripts/sys_voice-run.sh         # Continuous mode
```

---

## Migration Notes

This directory **consolidates** scripts from the old `ops/` and `tools/` directories:

- **ops/** → all operational scripts moved to `scripts/` with prefix `sys_`, `diag_`, or `util_`  
- **tools/** → all development tools moved to `scripts/` with prefix `dev_`, `diag_`, or `util_`  

Detailed mapping of moves can be found in **`SCRIPTS_MIGRATION_SUMMARY.md`** in the archive.

---

## Best Practices

1. **Use absolute paths** or automatic repository directory detection  
2. **Log information to stderr**, output data to stdout  
3. **Use `set -euo pipefail`** in bash scripts for fast error detection  
4. **Make scripts idempotent**, so repeated execution doesn't cause side effects  
5. **Add usage information** in script header or via `--help` option  

---

## Related Documentation

- `docs/ops/` – detailed descriptions of operational scripts  
- `docs/archive/SCRIPTS_MIGRATION_SUMMARY.md` – complete migration information  
- `Makefile` – build system integration  

---

**Last updated:** October 2025 (PR #13 – ops/tools consolidation)
