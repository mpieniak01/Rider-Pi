#!/usr/bin/env python3
"""
Validate systemd service files - check that all ExecStart paths exist.

This script parses all .service files in the systemd/ directory and validates
that the executables referenced in ExecStart, ExecStartPre, and ExecStartPost
directives exist in the repository or are system binaries.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def get_repo_root() -> Path:
    """Get repository root directory."""
    return Path(__file__).resolve().parents[1]


def parse_exec_line(line: str) -> list[str]:
    """
    Parse an Exec* line and extract executable paths.
    
    Handles:
    - Simple paths: /usr/bin/python3
    - Wrapped commands: /bin/bash -lc '...'
    - Commands with env: /usr/bin/env bash -lc '...'
    """
    # Remove directive prefix
    line = re.sub(r'^Exec\w+=', '', line).strip()
    
    # Handle special characters like @ and - prefixes
    line = re.sub(r'^[@-]+', '', line)
    
    paths = []
    
    # Skip bash -c/lc wrapped commands as they contain shell code
    if re.search(r'\b(bash|sh)\s+-[lc]', line):
        # Look for Python scripts called within shell commands
        # Pattern: python3 path/to/script.py
        python_scripts = re.findall(r'python3?\s+([/\w.-]+\.py)', line)
        paths.extend(python_scripts)
        return paths
    
    # Extract the first token (the actual executable)
    # Skip common wrappers like /usr/bin/env, /usr/bin/flock, etc.
    tokens = line.split()
    skip_next = False
    
    for i, token in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue
            
        # Skip options
        if token.startswith('-'):
            # Some options take values
            if token in ('-n', '-C'):
                skip_next = True
            continue
        
        # Check if it's a path
        if '/' in token:
            # Skip URLs
            if token.startswith('http://') or token.startswith('https://'):
                continue
            # Skip redirections
            if re.match(r'^\d*[<>]', token):
                continue
            # Skip common wrappers
            if token in ('/usr/bin/env', '/usr/bin/flock', '/bin/bash', '/bin/sh', '/usr/bin/make'):
                continue
            
            paths.append(token)
            break  # Usually only need first real path
    
    return paths


def validate_service_file(service_path: Path, repo_root: Path) -> tuple[bool, list[str]]:
    """
    Validate a single service file.
    
    Returns:
        (all_valid, error_messages)
    """
    errors = []
    
    try:
        with open(service_path) as f:
            content = f.read()
    except Exception as e:
        return False, [f"Failed to read {service_path}: {e}"]
    
    # Find all Exec* directives
    exec_lines = re.findall(r'^Exec\w+=.*$', content, re.MULTILINE)
    
    for line in exec_lines:
        paths = parse_exec_line(line)
        
        for path_str in paths:
            # Skip if it's a variable reference
            if '$' in path_str or '%' in path_str:
                continue
                
            # Convert to Path
            path = Path(path_str)
            
            # Check if it's an absolute system path
            if path.is_absolute():
                # System binaries - check common locations
                if path_str.startswith(('/usr/bin/', '/bin/', '/usr/sbin/', '/sbin/')):
                    # These are system binaries, we trust they exist on target system
                    continue
                
                # Check if it's a path within /home/pi/robot
                if path_str.startswith('/home/pi/robot/'):
                    # Convert to relative path for checking in repo
                    rel_path = path_str.replace('/home/pi/robot/', '')
                    check_path = repo_root / rel_path
                    
                    if not check_path.exists():
                        errors.append(
                            f"  ✗ {service_path.name}: Path does not exist: {path_str}\n"
                            f"    Expected at: {check_path}"
                        )
                        continue
                
                # Check if it's /workspaces path (incorrect)
                if path_str.startswith('/workspaces/'):
                    errors.append(
                        f"  ✗ {service_path.name}: Uses /workspaces path (should be /home/pi/robot): {path_str}"
                    )
                    continue
            else:
                # Relative path - check against working directory
                # Should be relative to /home/pi/robot
                check_path = repo_root / path_str
                if not check_path.exists():
                    errors.append(
                        f"  ✗ {service_path.name}: Relative path does not exist: {path_str}\n"
                        f"    Expected at: {check_path}"
                    )
    
    return len(errors) == 0, errors


def main():
    """Main validation routine."""
    repo_root = get_repo_root()
    systemd_dir = repo_root / "systemd"
    
    if not systemd_dir.exists():
        print(f"ERROR: systemd directory not found at {systemd_dir}")
        return 1
    
    print(f"Validating systemd service files in: {systemd_dir}")
    print(f"Repository root: {repo_root}\n")
    
    service_files = sorted(systemd_dir.glob("*.service"))
    
    if not service_files:
        print("No .service files found!")
        return 1
    
    all_valid = True
    total_errors = []
    
    for service_file in service_files:
        valid, errors = validate_service_file(service_file, repo_root)
        
        if valid:
            print(f"  ✓ {service_file.name}")
        else:
            all_valid = False
            print(f"  ✗ {service_file.name}")
            total_errors.extend(errors)
    
    if total_errors:
        print("\nErrors found:")
        for error in total_errors:
            print(error)
    
    print(f"\nTotal service files checked: {len(service_files)}")
    
    if all_valid:
        print("✓ All service files validated successfully!")
        return 0
    else:
        print(f"✗ Found {len(total_errors)} error(s)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
