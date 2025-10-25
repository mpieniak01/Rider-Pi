#!/usr/bin/env python3
"""
Auto-update documentation references to new script names and commands.
Based on SCRIPTS_MIGRATION_SUMMARY.md and repo-first rules.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()


def extract_migrations_from_summary() -> dict[str, str]:
    """Extract old → new mappings from SCRIPTS_MIGRATION_SUMMARY.md."""
    summary_file = REPO_ROOT / "docs/_pr_summaries/SCRIPTS_MIGRATION_SUMMARY.md"

    mappings = {}

    with open(summary_file) as f:
        content = f.read()

    # Extract table rows like: | ops/file.py | scripts/new_file.py |
    table_pattern = r'\|\s*([^\|]+?)\s*\|\s*([^\|]+?)\s*\|'

    for match in re.finditer(table_pattern, content):
        old_path = match.group(1).strip()
        new_path = match.group(2).strip()

        # Skip header rows
        if old_path in ['Old Path', 'Źródło', '--------', 'Source', 'Cel', 'Domena']:
            continue

        # Only add if it looks like a file path
        if '/' in old_path and '/' in new_path:
            mappings[old_path] = new_path

    return mappings


def add_repo_first_rules(mappings: dict[str, str]) -> dict[str, str]:
    """Add repo-first command mappings and rules."""

    # Ensure no duplicates from summary - prioritize these rules
    # LCD commands - prefer make targets
    cmd_mappings = {
        r'python3 (\.\/)?ops/lcdctl\.py on': 'make lcd-on',
        r'python3 (\.\/)?ops/lcdctl\.py off': 'make lcd-off',
        r'python3 (\.\/)?tools/lcdctl\.py on': 'make lcd-on',
        r'python3 (\.\/)?tools/lcdctl\.py off': 'make lcd-off',
    }

    # Add explicit file path mappings
    explicit_mappings = {
        'scripts/splash_device_info.py': 'scripts/sys_splash-info.py',
        'scripts/splash_device_info.sh': 'scripts/sys_splash-info.sh',
        'ops/splash_device_info.py': 'scripts/sys_splash-info.py',
        'ops/splash_device_info.sh': 'scripts/sys_splash-info.sh',
        'ops/boot_prepare.sh': 'scripts/sys_boot-prepare.sh',
        'scripts/boot_prepare.sh': 'scripts/sys_boot-prepare.sh',
        'tools/lcdctl.py': 'scripts/sys_lcd-control.py',
        'ops/lcdctl.py': 'scripts/sys_lcd-control.py',
        # Fix: actual file is systemd-sync.sh not sys_systemd-sync.sh
        'ops/systemd_sync.sh': 'scripts/systemd-sync.sh',
        'scripts/sys_systemd-sync.sh': 'scripts/systemd-sync.sh',
    }

    # Merge - explicit mappings override
    result = {**mappings, **explicit_mappings, **cmd_mappings}

    return result


def verify_new_path_exists(new_path: str) -> bool:
    """Verify that the new path exists in the repository."""
    # Skip command mappings (like 'make lcd-on')
    if new_path.startswith('make '):
        # Check if it's a Makefile target
        makefile = REPO_ROOT / "Makefile"
        if makefile.exists():
            target = new_path.replace('make ', '')
            with open(makefile) as f:
                content = f.read()
                # Check for target definition
                if re.search(rf'^{re.escape(target)}:', content, re.MULTILINE):
                    return True
        return False

    # Check file path
    file_path = REPO_ROOT / new_path
    return file_path.exists()


def should_skip_context(line: str, context_before: list[str], filepath: Path) -> bool:
    """
    Check if this line is in a context where we should NOT update.
    E.g., in migration summary tables showing old→new mappings.
    """
    # Always skip these files - they document the mappings/automation
    skip_files = [
        'SCRIPTS_MIGRATION_SUMMARY.md',
        'DOCS_AUTO_UPDATE.md',  # Documents the automation tool itself
    ]
    if any(skip_file in str(filepath) for skip_file in skip_files):
        return True

    # Check if we're in a markdown table (starts with |)
    if line.strip().startswith('|') and '|' in line:
        # Check if this is a migration table by looking at headers
        for prev_line in context_before[-10:]:
            if '|' in prev_line and any(
                header in prev_line
                for header in [
                    'Old Path',
                    'New Path',
                    'Źródło',
                    'Cel',
                    'Source',
                    'Target',
                    'Before',
                    'After',
                    'Was',
                    'Now',
                ]
            ):
                return True

    # Check if line itself is showing a migration mapping with arrow
    if '→' in line:
        # This is likely documenting a migration
        return True

    # Check if in a code block showing old vs new comparison
    if any(
        marker in line.lower()
        for marker in ['# old:', '# before:', 'old path', 'removed in pr', 'was a stub', 'moved from', 'migrated from']
    ):
        return True

    return False


def mark_deprecated_service(line: str, context_before: list[str]) -> tuple[str, bool]:
    """Mark deprecated services like rider-dispatcher.service."""
    deprecated_services = ['rider-dispatcher.service']

    updated = False
    for service in deprecated_services:
        if service in line and '(deprecated)' not in line.lower():
            # Check if current line or context already indicates it's deprecated/legacy/masked
            full_context = ' '.join(context_before[-3:] + [line]).lower()
            if any(word in full_context for word in ['legacy', 'deprecated', 'obsolete', 'mask', 'przestarzałe']):
                # Context already indicates deprecation, skip
                continue

            # Add (deprecated) marker if not already indicated
            line = line.replace(service, f'{service} (deprecated)')
            updated = True

    return line, updated


def update_file_references(content: str, mappings: dict[str, str], filepath: Path) -> tuple[str, list[str]]:
    """
    Update file and command references in markdown content.
    Returns (updated_content, list_of_changes).
    """
    lines = content.split('\n')
    updated_lines = []
    changes = []

    for i, line in enumerate(lines):
        context_before = lines[max(0, i - 5) : i]

        # Skip if in a context we shouldn't update
        if should_skip_context(line, context_before, filepath):
            updated_lines.append(line)
            continue

        # Check for deprecated services
        line, was_updated = mark_deprecated_service(line, context_before)
        if was_updated:
            changes.append(f"Line {i + 1}: Marked deprecated service")

        # Try to update references
        for old_ref, new_ref in mappings.items():
            # Check if this is a regex pattern (command mapping)
            if old_ref.startswith(r'python3') or '\\' in old_ref:
                # It's a regex pattern
                pattern = re.compile(old_ref)
                if pattern.search(line):
                    # Verify new path exists
                    if verify_new_path_exists(new_ref):
                        new_line = pattern.sub(new_ref, line)
                        if new_line != line:
                            changes.append(f"Line {i + 1}: {old_ref} → {new_ref}")
                            line = new_line
                    else:
                        print(
                            f"WARNING: {filepath.relative_to(REPO_ROOT)} line {i + 1}: "
                            f"Target {new_ref} not found, skipping update",
                            file=sys.stderr,
                        )
            else:
                # Simple string replacement for file paths
                if old_ref in line:
                    # Verify new path exists
                    if verify_new_path_exists(new_ref):
                        new_line = line.replace(old_ref, new_ref)
                        if new_line != line:
                            changes.append(f"Line {i + 1}: {old_ref} → {new_ref}")
                            line = new_line
                    else:
                        print(
                            f"WARNING: {filepath.relative_to(REPO_ROOT)} line {i + 1}: "
                            f"File {new_ref} not found, skipping update",
                            file=sys.stderr,
                        )

        updated_lines.append(line)

    return '\n'.join(updated_lines), changes


def scan_and_update_docs(mappings: dict[str, str], dry_run: bool = False) -> dict[str, list[str]]:
    """
    Scan all markdown files and update references.
    Returns dict of {filepath: list_of_changes}.
    """
    docs_dir = REPO_ROOT / "docs"

    # Find all markdown files
    md_files = list(docs_dir.rglob("*.md"))

    # Also check root-level md files
    md_files.extend(REPO_ROOT.glob("*.md"))

    all_changes = {}

    for md_file in sorted(md_files):
        try:
            with open(md_file, encoding='utf-8') as f:
                content = f.read()

            updated_content, changes = update_file_references(content, mappings, md_file)

            if changes:
                all_changes[str(md_file.relative_to(REPO_ROOT))] = changes

                if not dry_run:
                    # Write updated content
                    with open(md_file, 'w', encoding='utf-8') as f:
                        f.write(updated_content)
                    print(f"✓ Updated {md_file.relative_to(REPO_ROOT)}")
                else:
                    print(f"Would update {md_file.relative_to(REPO_ROOT)}")

        except Exception as e:
            print(f"Error processing {md_file}: {e}", file=sys.stderr)

    return all_changes


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Update documentation references')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without modifying files')
    parser.add_argument('--verify-only', action='store_true', help='Only verify that new paths exist')

    args = parser.parse_args()

    # Build migration map
    print("Building migration map...")
    mappings = extract_migrations_from_summary()
    mappings = add_repo_first_rules(mappings)

    print(f"Total mappings: {len(mappings)}")

    if args.verify_only:
        print("\nVerifying new paths exist...")
        missing = []
        for old, new in sorted(mappings.items()):
            if not verify_new_path_exists(new):
                missing.append((old, new))

        if missing:
            print(f"\n❌ Found {len(missing)} mappings where target doesn't exist:")
            for old, new in missing:
                print(f"  {old} → {new}")
            return 1
        else:
            print("✓ All target paths verified!")
            return 0

    # Scan and update
    print(f"\nScanning markdown files... (dry_run={args.dry_run})")
    all_changes = scan_and_update_docs(mappings, dry_run=args.dry_run)

    # Summary
    print("\n" + "=" * 60)
    if all_changes:
        print(f"{'Would update' if args.dry_run else 'Updated'} {len(all_changes)} file(s):\n")
        total_changes = 0
        for filepath, changes in sorted(all_changes.items()):
            print(f"\n{filepath}:")
            for change in changes:
                print(f"  {change}")
            total_changes += len(changes)

        print(f"\nTotal changes: {total_changes}")
    else:
        print("No changes needed - all documentation is up to date!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
