#!/usr/bin/env python3
"""
Validate documentation links and references.
Checks that all file paths and Makefile targets referenced in .md files exist.
"""
import re
import sys
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).parent.parent.resolve()


def extract_file_references(content: str) -> List[str]:
    """Extract file path references from markdown content."""
    references = []
    
    # Pattern 1: scripts/xxx.py or scripts/xxx.sh
    script_pattern = r'scripts/[\w\-_]+\.(?:py|sh)'
    references.extend(re.findall(script_pattern, content))
    
    # Pattern 2: ops/xxx or tools/xxx (should not exist anymore)
    legacy_pattern = r'(?:ops|tools)/[\w\-_]+\.(?:py|sh)'
    legacy_refs = re.findall(legacy_pattern, content)
    
    # Pattern 3: Markdown links [text](path)
    md_link_pattern = r'\[([^\]]+)\]\((?!http)([^)]+)\)'
    md_links = re.findall(md_link_pattern, content)
    references.extend([link[1] for link in md_links if not link[1].startswith('#')])
    
    return references, legacy_refs


def extract_makefile_targets(content: str) -> List[str]:
    """Extract Makefile target references (make xxx) from markdown."""
    # Pattern: make target-name
    pattern = r'make\s+([\w\-]+)'
    return re.findall(pattern, content)


def verify_file_exists(filepath: str, source_file: Path) -> bool:
    """Verify that a file path exists relative to repo root or source file."""
    # Try relative to repo root
    abs_path = REPO_ROOT / filepath
    if abs_path.exists():
        return True
    
    # Try relative to source file directory
    rel_path = source_file.parent / filepath
    if rel_path.exists():
        return True
    
    return False


def verify_makefile_target(target: str) -> bool:
    """Verify that a Makefile target exists."""
    makefile = REPO_ROOT / "Makefile"
    if not makefile.exists():
        return False
    
    with open(makefile, 'r') as f:
        content = f.read()
    
    # Look for target definition: ^target: or ^.PHONY: target
    pattern = rf'^{re.escape(target)}:|^\.PHONY:.*\b{re.escape(target)}\b'
    return bool(re.search(pattern, content, re.MULTILINE))


def scan_markdown_file(filepath: Path) -> Tuple[List[str], List[str]]:
    """
    Scan a markdown file for references.
    Returns (list of errors, list of warnings).
    """
    errors = []
    warnings = []
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        errors.append(f"Could not read file: {e}")
        return errors, warnings
    
    # Extract references
    file_refs, legacy_refs = extract_file_references(content)
    make_targets = extract_makefile_targets(content)
    
    # Check legacy references (should not exist in active docs)
    if legacy_refs:
        # Skip migration summary - it documents legacy paths
        if 'SCRIPTS_MIGRATION_SUMMARY.md' not in str(filepath):
            for ref in set(legacy_refs):
                warnings.append(f"Legacy reference found: {ref}")
    
    # Verify file references exist
    for ref in set(file_refs):
        if not verify_file_exists(ref, filepath):
            # Skip if it's in a comment or migration doc context
            if 'SCRIPTS_MIGRATION' not in str(filepath):
                errors.append(f"File not found: {ref}")
    
    # Verify Makefile targets exist
    for target in set(make_targets):
        if not verify_makefile_target(target):
            # Some common false positives
            if target not in ['install', 'build', 'run', 'example']:
                warnings.append(f"Makefile target not found: make {target}")
    
    return errors, warnings


def main():
    """Main entry point."""
    docs_dir = REPO_ROOT / "docs"
    
    # Find all markdown files
    md_files = list(docs_dir.rglob("*.md"))
    md_files.extend(REPO_ROOT.glob("*.md"))
    
    total_errors = 0
    total_warnings = 0
    files_with_issues = 0
    
    print("Validating documentation references...\n")
    
    for md_file in sorted(md_files):
        errors, warnings = scan_markdown_file(md_file)
        
        if errors or warnings:
            files_with_issues += 1
            rel_path = md_file.relative_to(REPO_ROOT)
            print(f"\n{rel_path}:")
            
            for error in errors:
                print(f"  ❌ ERROR: {error}")
                total_errors += 1
            
            for warning in warnings:
                print(f"  ⚠️  WARNING: {warning}")
                total_warnings += 1
    
    # Summary
    print("\n" + "="*60)
    print(f"Scanned {len(md_files)} markdown files")
    print(f"Files with issues: {files_with_issues}")
    print(f"Total errors: {total_errors}")
    print(f"Total warnings: {total_warnings}")
    
    if total_errors > 0:
        print("\n❌ Validation FAILED - fix errors above")
        return 1
    elif total_warnings > 0:
        print("\n⚠️  Validation passed with warnings")
        return 0
    else:
        print("\n✅ All documentation references validated successfully!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
