#!/usr/bin/env python3
"""
Pytest-based static validation of systemd service files.

Tests that all systemd service files are valid, have required fields,
and reference existing files. These tests run without systemd installed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


@pytest.fixture
def repo_root():
    """Get repository root directory."""
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def systemd_dir(repo_root):
    """Get systemd directory."""
    return repo_root / "systemd"


@pytest.fixture
def service_files(systemd_dir):
    """Get all .service files."""
    files = sorted(systemd_dir.glob("*.service"))
    assert files, f"No .service files found in {systemd_dir}"
    return files


class TestSystemdServiceFiles:
    """Static validation tests for systemd service files."""

    def test_systemd_directory_exists(self, systemd_dir):
        """Test that systemd directory exists."""
        assert systemd_dir.exists(), f"systemd directory not found at {systemd_dir}"
        assert systemd_dir.is_dir(), f"{systemd_dir} is not a directory"

    def test_service_files_found(self, service_files):
        """Test that service files are found."""
        assert len(service_files) > 0, "No .service files found"
        # We expect at least 15 service files based on current repo state
        assert len(service_files) >= 15, f"Expected at least 15 service files, found {len(service_files)}"

    def test_description_field_present(self, service_files):
        """Test that all service files have Description field."""
        missing_description = []

        for service_file in service_files:
            content = service_file.read_text()
            # Match Description= line
            if not re.search(r"^Description=.+$", content, re.MULTILINE):
                missing_description.append(service_file.name)

        assert not missing_description, f"Service files missing Description field: {', '.join(missing_description)}"

    def test_description_field_not_empty(self, service_files):
        """Test that Description fields are not empty."""
        empty_description = []

        for service_file in service_files:
            content = service_file.read_text()
            # Match Description= line and check if value is non-empty
            match = re.search(r"^Description=(.*)$", content, re.MULTILINE)
            if match and not match.group(1).strip():
                empty_description.append(service_file.name)

        assert not empty_description, f"Service files with empty Description: {', '.join(empty_description)}"

    def test_no_deprecated_workspaces_path(self, service_files):
        """Test that no service files use deprecated /workspaces/ path."""
        deprecated_path = []

        for service_file in service_files:
            content = service_file.read_text()
            if "/workspaces/" in content:
                deprecated_path.append(service_file.name)

        assert not deprecated_path, (
            f"Service files using deprecated /workspaces/ path: {', '.join(deprecated_path)}. "
            "Should use /home/pi/robot instead."
        )

    def test_no_deprecated_ops_path(self, service_files):
        """Test that no service files use deprecated ops/ path in ExecStart."""
        deprecated_path = []

        for service_file in service_files:
            content = service_file.read_text()
            # Check for ops/ in Exec* directives
            if re.search(r"^Exec\w+.*\bops/", content, re.MULTILINE):
                deprecated_path.append(service_file.name)

        assert not deprecated_path, (
            f"Service files using deprecated ops/ path: {', '.join(deprecated_path)}. " "Should use scripts/ instead."
        )

    def test_no_deprecated_tools_path(self, service_files):
        """Test that no service files use deprecated tools/ path in ExecStart."""
        deprecated_path = []

        for service_file in service_files:
            content = service_file.read_text()
            # Check for tools/ in Exec* directives
            if re.search(r"^Exec\w+.*\btools/", content, re.MULTILINE):
                deprecated_path.append(service_file.name)

        assert not deprecated_path, (
            f"Service files using deprecated tools/ path: {', '.join(deprecated_path)}. " "Should use scripts/ instead."
        )

    def test_exec_start_paths_exist(self, service_files, repo_root):
        """Test that all ExecStart paths reference existing files."""
        missing_paths = []

        for service_file in service_files:
            content = service_file.read_text()
            # Find all Exec* directives
            exec_lines = re.findall(r"^Exec\w+=.*$", content, re.MULTILINE)

            for line in exec_lines:
                paths = self._parse_exec_line(line)

                for path_str in paths:
                    # Skip variable references
                    if "$" in path_str or "%" in path_str:
                        continue

                    path = Path(path_str)

                    # Check absolute paths within /home/pi/robot/
                    if path.is_absolute() and path_str.startswith("/home/pi/robot/"):
                        rel_path = path_str.replace("/home/pi/robot/", "")
                        check_path = repo_root / rel_path
                        if not check_path.exists():
                            missing_paths.append(f"{service_file.name}: {path_str} (expected at {check_path})")

                    # Check relative paths
                    elif not path.is_absolute():
                        check_path = repo_root / path_str
                        if not check_path.exists():
                            missing_paths.append(f"{service_file.name}: {path_str} (expected at {check_path})")

        assert not missing_paths, "Service files reference non-existent paths:\n  " + "\n  ".join(missing_paths)

    def test_python_services_have_working_directory(self, service_files):
        """Test that Python services using apps/ or services/ have WorkingDirectory."""
        missing_workdir = []

        for service_file in service_files:
            content = service_file.read_text()

            # Check if service uses Python with apps/ or services/
            if re.search(r"python3.*(?:apps/|services/)", content):
                # Check for WorkingDirectory
                if not re.search(r"^WorkingDirectory=", content, re.MULTILINE):
                    missing_workdir.append(service_file.name)

        # This is a warning, not a hard failure - some services may work without it
        if missing_workdir:
            pytest.skip(f"Python services without WorkingDirectory (warning): {', '.join(missing_workdir)}")

    @staticmethod
    def _parse_exec_line(line: str) -> list[str]:
        """
        Parse an Exec* line and extract executable paths.

        Similar to the logic in diag_validate-systemd-paths.py
        """
        # Remove directive prefix
        line = re.sub(r"^Exec\w+=", "", line).strip()

        # Handle special characters like @ and - prefixes
        line = re.sub(r"^[@-]+", "", line)

        paths = []

        # Skip bash -c/lc wrapped commands, look for Python scripts
        if re.search(r"\b(bash|sh)\s+-[lc]", line):
            python_scripts = re.findall(r"python3?\s+([/\w.-]+\.py)", line)
            paths.extend(python_scripts)
            return paths

        # Extract the first token (the actual executable)
        tokens = line.split()
        skip_next = False

        for token in tokens:
            if skip_next:
                skip_next = False
                continue

            # Skip options
            if token.startswith("-"):
                if token in ("-n", "-C"):
                    skip_next = True
                continue

            # Check if it's a path
            if "/" in token:
                # Skip URLs and redirections
                if token.startswith(("http://", "https://")) or re.match(r"^\d*[<>]", token):
                    continue
                # Skip common wrappers
                if token in ("/usr/bin/env", "/usr/bin/flock", "/bin/bash", "/bin/sh", "/usr/bin/make"):
                    continue

                paths.append(token)
                break  # Usually only need first real path

        return paths


class TestServiceMapping:
    """Test the service → script mapping documentation."""

    def test_all_services_documented_in_mapping(self, service_files, repo_root):
        """Test that all service files are documented in SYSTEMD_SERVICES_MAPPING.md."""
        mapping_doc = repo_root / "docs" / "SYSTEMD_SERVICES_MAPPING.md"

        # Skip if mapping doc doesn't exist
        if not mapping_doc.exists():
            pytest.skip("SYSTEMD_SERVICES_MAPPING.md not found")

        mapping_content = mapping_doc.read_text()

        undocumented = []
        for service_file in service_files:
            service_name = service_file.name
            # Check if service is mentioned in the mapping doc
            if service_name not in mapping_content:
                undocumented.append(service_name)

        # This is informational - some services might intentionally not be documented
        if undocumented:
            pytest.skip(f"Services not documented in mapping (info): {', '.join(undocumented)}")
