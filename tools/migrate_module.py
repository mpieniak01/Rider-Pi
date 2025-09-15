#!/usr/bin/env python3
"""
Migrate one module from _apps/<module> → apps/<module> safely.

Usage:
  python3 tools/migrate_module.py <module> [--dry-run] [--only_if_stub] [--backup]

Behavior:
  - Copies files from _apps/<module>/ to apps/<module>/.
  - By default, overwrite only if target is smaller than 400 bytes or contains 'pass' / 'NotImplementedError'.
  - With --only_if_stub, keep this behavior; otherwise overwrite all differing files.
  - With --backup, write a .bak alongside any overwritten file.
  - Always skips __pycache__, .ipynb_checkpoints.

Exit code:
  0 on success, non-zero on failure.
"""
import argparse, os, sys, shutil, re
from pathlib import Path

STUB_RE = re.compile(r'^\s*(class|def)\s+\w+\(?.*:\s*pass\s*$', re.M)

def is_stub_py(path: Path) -> bool:
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    if len(txt) < 400: return True
    if "NotImplementedError" in txt: return True
    if "pass\n" in txt: return True
    if STUB_RE.search(txt): return True
    return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("module")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only_if_stub", action="store_true")
    ap.add_argument("--backup", action="store_true")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    src = repo_root / "_apps" / args.module
    dst = repo_root / "apps" / args.module

    if not src.exists():
        print(f"[ERR] Source module not found: {src}", file=sys.stderr)
        return 2
    if not dst.exists():
        print(f"[INFO] Target missing, creating: {dst}")
        if not args.dry_run:
            dst.mkdir(parents=True, exist_ok=True)

    copied = 0; skipped = 0
    for sp in src.rglob("*"):
        rel = sp.relative_to(src)
        dp = dst / rel
        if sp.is_dir():
            if "__pycache__" in sp.parts or ".ipynb_checkpoints" in sp.parts:
                continue
            if not args.dry_run:
                dp.mkdir(parents=True, exist_ok=True)
            continue
        # files
        if sp.suffix == ".pyc" or ".ipynb_checkpoints" in sp.parts:
            continue
        do_copy = True
        reason = "overwrite"
        if dp.exists():
            if args.only_if_stub and dp.suffix == ".py" and not is_stub_py(dp):
                do_copy = False
                reason = "target-not-stub"
            else:
                # compare content
                try:
                    s = sp.read_bytes(); d = dp.read_bytes()
                    if s == d:
                        do_copy = False
                        reason = "identical"
                except Exception:
                    pass
        else:
            reason = "new"

        if do_copy:
            print(f"[COPY] {rel}  ({reason})")
            if not args.dry_run:
                dp.parent.mkdir(parents=True, exist_ok=True)
                if args.backup and dp.exists():
                    dp_backup = dp.with_suffix(dp.suffix + ".bak")
                    shutil.copy2(dp, dp_backup)
                shutil.copy2(sp, dp)
            copied += 1
        else:
            print(f"[SKIP] {rel}  ({reason})")
            skipped += 1

    print(f"[DONE] copied={copied}, skipped={skipped}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
