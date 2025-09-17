# Face LCD Migration Documentation

## Overview

This document outlines the migration process from the `_apps` directory to the `apps` directory for the Face LCD project. The goal is to eliminate any dependencies on the `_apps` path while introducing a new driver structure and a fast-path for RAW RGB565 image processing.

## Migration Goals

1. **Remove Dependencies**: Ensure that no code in the Face LCD rendering path imports from `_apps`.
2. **New Driver Structure**: Implement a new driver located in `apps/ui/face/driver/` with the following components:
   - `mock.py`: A mock backend for CI that saves images to `/tmp/face_last.png` and `/tmp/face_last.rgb565`.
   - `spi.py`: An optional hardware backend that is not used in CI.
3. **Fast-Path RAW RGB565**: Introduce a fast-path for processing images in RAW RGB565 format, with a fallback mechanism.
4. **Unified Configuration**: Centralize panel configuration settings such as rotation and color format in `panel_cfg.py`.

## Implementation Details

### Directory Structure

- **apps/ui/face/driver/**
  - `__init__.py`: Exports a factory function `make_driver(kind: Literal["mock","spi"], cfg: PanelCfg) -> Driver`.
  - `mock.py`: Implements the default backend for CI.
  - `spi.py`: Contains the optional hardware backend.

- **apps/ui/face/panel_cfg.py**: Defines the `PanelCfg` class with properties for rotation and color format.

- **apps/ui/face/face_io.py**: Contains image conversion functions:
  - `to_rgb565(img: Image) -> bytes`
  - `apply_rotate(img: Image, deg: int) -> Image`
  - `fit_strategy(img, mode: Literal["fill","fit","stretch"]) -> Image`

- **tools/**: Contains CLI tools for interacting with the Face LCD.
  - `newface_lcd_direct.py`: Implements the CLI with a `--force` switch for different modes.
  - `face_cli.py`: A simple CLI with various options for controlling the Face LCD.

### Testing

New tests have been added to ensure the functionality of the migration:
- `tests/test_face_raw_fastpath.py`: Validates the correct size of the RGB565 buffer and checks for metadata presence.
- `tests/test_no_underscore_apps_dependency.py`: Asserts that there are no imports from `_apps` in key files.

### Documentation Updates

The README.md and AGENT.md files have been updated to reflect the changes made during the migration process. The README includes instructions for running the mock and fast-path, while AGENT.md summarizes the changes and provides command-line usage.

## Conclusion

This migration enhances the maintainability and clarity of the Face LCD project by removing legacy dependencies and introducing a more structured approach to image processing. The new driver architecture and fast-path capabilities will improve performance and facilitate future development.