# AGENT.md

# Face LCD Migration - Agent Notes

## Migration Summary
This document outlines the changes made during the migration of the Face LCD functionality from the `_apps` directory to the `apps` directory. The goal was to eliminate any dependencies on `_apps` while introducing a new driver structure and maintaining the ability to run scripts manually without altering systemd configurations.

## Key Changes
- **Removal of `_apps` Dependency**: All references to `_apps` have been eliminated from the Face LCD codebase.
- **New Driver Structure**: Introduced a new driver system located in `apps/ui/face/driver/` with a default mock backend for CI and an optional SPI backend for hardware.
- **Fast-Path RAW RGB565**: Implemented a fast-path for RAW RGB565 image processing, with a fallback mechanism.
- **Unified Configuration**: Centralized panel configuration settings in `panel_cfg.py`, allowing for consistent image transformations.
- **CLI Enhancements**: Updated CLI tools to support new options and configurations, ensuring ease of use.

## Commands to Run
To run the Face LCD migration in a development or CI environment without hardware, use the following commands:

```bash
export RIDER_APPS_PATH="_apps:apps"
export FACE_LCD_BACKEND=mock
export FACE_LCD_ROTATE=270
export FACE_LCD_SPI_HZ=32000000
export FACE_LCD_FIT=fill

python3 -m compileall -q services/api_core/*.py services/api_server.py apps/ui/face/*.py
pytest -q tests/test_face_anim_api.py
pytest -q tests/test_face_raw_fastpath.py
pytest -q tests/test_no_underscore_apps_dependency.py
python3 tools/face_cli.py --expr happy --rotate 270 --force raw:rgb565 --stats
ls -lah /tmp/face_last.*
```

## Testing
- Ensure that all tests pass, including:
  - `tests/test_face_anim_api.py`
  - `tests/test_face_raw_fastpath.py`
  - `tests/test_no_underscore_apps_dependency.py`

## Documentation
Refer to `README.md` and `docs/face_lcd_migration.md` for detailed instructions on running the mock and fast-path features, as well as additional migration notes.