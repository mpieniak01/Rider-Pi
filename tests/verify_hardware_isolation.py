#!/usr/bin/env python3
"""
Verify that hardware library imports are only in drivers/ directory.
"""

import os
import re
import sys
from pathlib import Path


def find_hardware_imports(root_dir: Path, exclude_dirs: set):
    """
    Find all hardware library imports outside of drivers/ directory.

    Returns:
        List of tuples (file_path, line_number, import_statement)
    """
    hardware_patterns = [
        re.compile(r"^\s*from\s+xgolib\s+import"),
        re.compile(r"^\s*import\s+xgolib"),
        re.compile(r"^\s*from\s+spidev\s+import"),
        re.compile(r"^\s*import\s+spidev"),
        re.compile(r"^\s*from\s+RPi\.GPIO\s+import"),
        re.compile(r"^\s*import\s+RPi\.GPIO"),
    ]

    violations = []

    for py_file in root_dir.rglob("*.py"):
        # Skip excluded directories
        if any(excluded in str(py_file) for excluded in exclude_dirs):
            continue

        # Skip __pycache__ and other generated files
        if "__pycache__" in str(py_file) or ".pyc" in str(py_file):
            continue

        try:
            with open(py_file, encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    for pattern in hardware_patterns:
                        if pattern.match(line):
                            rel_path = py_file.relative_to(root_dir)
                            violations.append((str(rel_path), line_num, line.strip()))
        except (UnicodeDecodeError, PermissionError):
            # Skip binary files or files we can't read
            pass

    return violations


def main():
    repo_root = Path(__file__).parent.parent
    print(f"Checking for hardware imports in: {repo_root}")

    # Directories where hardware imports are allowed
    allowed_dirs = {
        "drivers",  # Hardware abstraction layer
        "scripts",  # Operational scripts (allowed to access hardware directly)
        "ops",  # Legacy ops subdirs (agent/, audio/)
        ".git",  # Git metadata
        "venv",  # Virtual environment
        ".venv",  # Virtual environment
        "__pycache__",  # Python cache
    }

    # Directories that need special consideration (allowed for specific use cases)
    special_dirs = {
        "apps/safety",  # E-stop and safety checks may need direct GPIO access
        "apps/ui/manager.py",  # UI manager may need GPIO for buttons
        "apps/hw",  # Hardware-specific application code
        "services/motion_bridge.py",  # Legacy bridge code
    }

    violations = find_hardware_imports(repo_root, allowed_dirs)

    # Filter out special cases
    critical_violations = []
    for file_path, line_num, line in violations:
        # Check if this is in a special directory
        is_special = any(special in file_path for special in special_dirs)
        if not is_special:
            critical_violations.append((file_path, line_num, line))

    print("\n" + "=" * 80)
    print("HARDWARE IMPORT VERIFICATION REPORT")
    print("=" * 80)

    if critical_violations:
        print(f"\n❌ CRITICAL: Found {len(critical_violations)} hardware imports outside drivers/:\n")
        for file_path, line_num, line in critical_violations:
            print(f"  {file_path}:{line_num}")
            print(f"    {line}")
        print("\nThese files should import from drivers/ instead of directly from hardware libraries.")
        return 1
    else:
        print("\n✅ SUCCESS: No critical hardware imports found outside drivers/")

    # Report special cases as informational
    special_violations = [v for v in violations if v not in critical_violations]
    if special_violations:
        print(f"\nℹ️  INFO: Found {len(special_violations)} hardware imports in special directories:")
        for file_path, line_num, line in special_violations:
            print(f"  {file_path}:{line_num}")
            print(f"    {line}")
        print("\nThese are allowed for operational/safety/utility purposes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
