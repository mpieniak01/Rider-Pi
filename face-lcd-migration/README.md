# Face LCD Migration

## Overview
This project aims to migrate the face rendering functionality from the legacy `_apps` structure to a new modular structure under `apps/ui/face`. The goal is to eliminate any dependencies on `_apps` while introducing a mock backend for continuous integration (CI) and a fast-path for RAW RGB565 image processing.

## Migration Details
- **Removal of `_apps` Dependency**: All references to `_apps` have been removed from the face rendering code. The new structure is fully contained within `apps/ui/face`.
- **New Driver Implementation**: A new driver system has been implemented in `apps/ui/face/driver`, which includes:
  - `mock.py`: The default backend for CI, which saves images to `/tmp/face_last.png` and `/tmp/face_last.rgb565`, along with metadata.
  - `spi.py`: An optional hardware backend that is not used in CI.

## Fast-Path RAW RGB565
- The project introduces a fast-path for processing images in RAW RGB565 format. This is achieved through command-line interface (CLI) tools that allow users to specify the desired output format.
- The CLI tools include:
  - `tools/newface_lcd_direct.py`: Implements a CLI for running scripts with a `--force` switch that supports modes: `raw:rgb565`, `push_frame:rgb565_3`, and `png`.
  - `tools/face_cli.py`: A simple CLI with options for expression, rotation, SPI frequency, fit strategy, and force mode.

## Configuration
- The configuration for panel settings, including rotation and color format, is centralized in `apps/ui/face/panel_cfg.py`.
- Environment variables and command-line arguments are used to configure the behavior of the application.

## Testing
- New tests have been added to ensure the correctness of the new implementation:
  - `tests/test_face_raw_fastpath.py`: Validates the size of the RGB565 buffer, rotation, fit strategy, and the presence of mock files.
  - `tests/test_no_underscore_apps_dependency.py`: Asserts that there are no imports from `_apps` in key files.

## Running the Project
To run the project in a development or CI environment without hardware, use the following commands:

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

## Documentation
For detailed information on the migration process and usage of the new features, refer to the following documents:
- [AGENT.md](AGENT.md): A summary of changes and commands for running the project.
- [docs/face_lcd_migration.md](docs/face_lcd_migration.md): Detailed documentation on the migration from `_apps` and the fast-path RAW implementation.