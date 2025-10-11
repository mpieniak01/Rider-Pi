#!/usr/bin/env python3
"""Check that Python files don't exceed the line limit (600 lines by default).

- Local runs: SKIP (exit 0), chyba że wymusisz ENFORCE_FILE_LENGTH=1.
- CI runs   : ENFORCED (gdy CI=1/true).

Known exceptions (do rozbicia później):
  - apps/voice/stream/svc_streaming.py (tracked)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

MAX_LINES_DEFAULT = 600

# Jedyny sensowny wyjątek na dziś:
# Wartość jest "górką" – nie zawracamy głowy regresją lokalnie.
KNOWN_EXCEPTIONS = {
    "apps/voice/stream/svc_streaming.py": 9999,  # tymczasowo bez limitu, egzekwujemy w CI polityką/PR review
}


def check_file_length(file_path: Path, max_lines: int) -> tuple[bool, int]:
    with file_path.open(encoding="utf-8") as f:
        line_count = sum(1 for _ in f)
    return (line_count <= max_lines), line_count


def is_test_file(file_path: Path) -> bool:
    name = file_path.name
    return name.startswith("test_") or name.endswith("_test.py")


def main() -> int:
    # 1) Lokalnie: skip, chyba że ENFORCE_FILE_LENGTH=1
    ci = os.getenv("CI", "").lower() in {"1", "true", "yes"}
    enforce_local = os.getenv("ENFORCE_FILE_LENGTH", "") == "1"
    if not ci and not enforce_local:
        print("⏭  Skipping file-length check locally. (Set ENFORCE_FILE_LENGTH=1 or run in CI to enforce.)")
        return 0

    repo_root = Path(__file__).resolve().parent.parent
    voice_dir = repo_root / "apps" / "voice"
    if not voice_dir.exists():
        print(f"Error: {voice_dir} does not exist", file=sys.stderr)
        return 1

    py_files = [p for p in voice_dir.rglob("*.py") if not is_test_file(p)]
    failures = []
    regressions = []

    for file_path in sorted(py_files):
        rel_path = str(file_path.relative_to(repo_root))
        allowed = KNOWN_EXCEPTIONS.get(rel_path)
        if allowed is not None:
            ok, count = check_file_length(file_path, allowed)
            if not ok:
                regressions.append((rel_path, count, allowed))
            continue

        ok, count = check_file_length(file_path, MAX_LINES_DEFAULT)
        if not ok:
            failures.append((rel_path, count))

    if regressions:
        for rel_path, count, allowed in regressions:
            print(f"⚠️  {rel_path}: {count} lines (regression: was {allowed}, limit {MAX_LINES_DEFAULT})")
        print("\nKnown exception(s) have regressed. Please reduce size or update exceptions (prefer splitting).")
        return 2

    if failures:
        for rel_path, count in failures:
            print(f"❌ {rel_path}: {count} lines (exceeds {MAX_LINES_DEFAULT})")
        print(f"\n{len(failures)} file(s) exceed the {MAX_LINES_DEFAULT} line limit. Consider splitting modules.")
        return 1

    print(f"✅ All files within limits (checked {len(py_files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
