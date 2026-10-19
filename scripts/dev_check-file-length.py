#!/usr/bin/env python3
"""Shared Python file-size policy for local hooks and CI: warn >600, fail >800."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

SOFT_LIMIT = 600
HARD_LIMIT = 800


def changed_files(root: Path, base: str, head: str) -> list[Path]:
    commits = []
    for ref in (base, head):
        if not ref or ref.startswith("-"):
            raise ValueError("invalid_git_reference")
        resolved = subprocess.check_output(
            ["git", "rev-parse", "--verify", "--end-of-options", ref + "^{commit}"], cwd=root, text=True
        ).strip()
        if len(resolved) != 40 or any(char not in "0123456789abcdef" for char in resolved):
            raise ValueError("invalid_git_commit")
        commits.append(resolved)
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRT", "-z", *commits, "--", "*.py"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / os.fsdecode(name) for name in result.stdout.split(b"\0") if name]


def check_files(paths: list[Path], *, root: Path, annotations: bool = False) -> int:
    failed = False
    for path in sorted(set(paths)):
        try:
            name = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
            if path.is_symlink():
                raise OSError("refusing to inspect symbolic links")
            if not path.is_file():
                raise OSError("not a regular file")
            with path.open(encoding="utf-8") as source:
                count = sum(1 for _ in source)
        except (OSError, UnicodeError) as exc:
            print(f"ERROR: cannot inspect {path}: {exc}")
            failed = True
            continue
        level = "error" if count > HARD_LIMIT else "warning" if count > SOFT_LIMIT else None
        if level is None:
            continue
        message = f"{count} lines; advisory limit {SOFT_LIMIT}, hard limit {HARD_LIMIT}."
        if annotations:
            # Escape GitHub workflow commands, including unusual tracked filenames.
            name = name.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            name = name.replace(":", "%3A").replace(",", "%2C")
            print(f"::{level} file={name},line=1::{message}")
        else:
            print(f"{level.upper()}: {name}: {message}")
        failed = failed or level == "error"
    if not failed:
        print(f"PASS: file-size policy (warning >{SOFT_LIMIT}, failure >{HARD_LIMIT}).")
    return int(failed)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Python files supplied by the local hook")
    parser.add_argument("--base", default="origin/main", help="Diff base for CI/manual runs")
    parser.add_argument("--head", default="HEAD", help="Diff head for CI/manual runs")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    try:
        paths = [root / path for path in args.paths] if args.paths else changed_files(root, args.base, args.head)
    except (subprocess.CalledProcessError, ValueError) as exc:
        detail = (getattr(exc, "stderr", b"") or b"").decode(errors="replace").strip() or str(exc)
        print(f"ERROR: cannot determine changed Python files: {detail}")
        return 1
    return check_files(paths, root=root, annotations=os.getenv("GITHUB_ACTIONS") == "true")


if __name__ == "__main__":
    raise SystemExit(main())
