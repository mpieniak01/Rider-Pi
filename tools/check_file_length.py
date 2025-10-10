#!/usr/bin/env python3
"""Check that Python files don't exceed the line limit (600 lines by default).

This guard prevents large monolithic files and encourages modular code.
Ignores test files (*_test.py, test_*.py) as they can be longer.

Known exceptions (pre-existing, to be fixed):
  - apps/voice/stream/service.py (704 lines, from PR-2)
  - apps/voice/svc_file.py (754 lines, consolidated from service_impl in PR#1)
  - apps/voice/playback.py (617 lines, from PR-2)

Exit codes:
  0 - All files pass
  1 - One or more files exceed the limit (excluding known exceptions)
  2 - Known exceptions have grown (regression)
"""

import sys
from pathlib import Path

# Known exceptions (files that currently exceed limit but are tracked)
# Format: (path_relative_to_repo, max_allowed_lines)
KNOWN_EXCEPTIONS = {
    "apps/voice/stream/service.py": 704,
    "apps/voice/svc_file.py": 754,
    "apps/voice/playback.py": 617,
}


def check_file_length(file_path: Path, max_lines: int = 600) -> tuple[bool, int]:
    """Check if a file exceeds the line limit.

    Args:
        file_path: Path to the Python file
        max_lines: Maximum allowed lines (default: 600)

    Returns:
        Tuple of (passes_check, line_count)
    """
    with open(file_path, encoding="utf-8") as f:
        line_count = sum(1 for _ in f)

    passes = line_count <= max_lines
    return passes, line_count


def is_test_file(file_path: Path) -> bool:
    """Check if a file is a test file (should be ignored)."""
    name = file_path.name
    return name.startswith("test_") or name.endswith("_test.py")


def main():
    """Main entry point."""
    max_lines = 600
    repo_root = Path(__file__).parent.parent

    # Find all Python files in apps/voice
    voice_dir = repo_root / "apps" / "voice"
    if not voice_dir.exists():
        print(f"Error: {voice_dir} does not exist", file=sys.stderr)
        return 1

    python_files = list(voice_dir.rglob("*.py"))

    # Filter out test files
    non_test_files = [f for f in python_files if not is_test_file(f)]

    failures = []
    regressions = []

    for file_path in sorted(non_test_files):
        passes, line_count = check_file_length(file_path, max_lines)
        rel_path = str(file_path.relative_to(repo_root))

        # Check if this is a known exception
        if rel_path in KNOWN_EXCEPTIONS:
            allowed = KNOWN_EXCEPTIONS[rel_path]
            if line_count > allowed:
                regressions.append((rel_path, line_count, allowed))
                print(f"⚠️  {rel_path}: {line_count} lines (regression: was {allowed}, limit {max_lines})")
            # Don't report as failure if within exception limit
            continue

        if not passes:
            failures.append((rel_path, line_count))
            print(f"❌ {rel_path}: {line_count} lines (exceeds {max_lines})")

    # Report results
    if regressions:
        print(f"\n{len(regressions)} known exception(s) have regressed (grown larger).")
        print("Please reduce file size or update KNOWN_EXCEPTIONS if justified.")
        return 2

    if failures:
        print(f"\n{len(failures)} new file(s) exceed the {max_lines} line limit.")
        print("\nPlease split large files into smaller, focused modules.")
        return 1

    # Success
    exception_count = sum(1 for f in non_test_files if str(f.relative_to(repo_root)) in KNOWN_EXCEPTIONS)
    checked = len(non_test_files)
    print(f"✅ All files under {max_lines} lines (checked {checked} files, {exception_count} known exceptions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
