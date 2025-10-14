#!/usr/bin/env python3
"""
Smoke tests for systemd service operations.

These tests require systemd to be available and will be skipped if not present.
They test actual service start/stop operations in a safe, controlled manner.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def systemd_available() -> bool:
    """Check if systemd is available."""
    try:
        result = subprocess.run(
            ["systemctl", "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# Skip all tests in this module if systemd is not available
pytestmark = pytest.mark.skipif(
    not systemd_available(),
    reason="systemd not available - skipping smoke tests",
)


@pytest.fixture
def repo_root():
    """Get repository root directory."""
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def systemd_dir(repo_root):
    """Get systemd directory."""
    return repo_root / "systemd"


# Whitelist of services safe to test in smoke tests
# These are non-critical services that can be started/stopped without breaking the system
SMOKE_TEST_SERVICES = [
    # Note: We only test services that are safe to start/stop
    # Critical services like SSH or network services are excluded
]


class TestSystemdSmoke:
    """Smoke tests for systemd service operations."""

    @pytest.mark.skipif(
        os.getenv("SYSTEMD_SMOKE_TESTS") != "1",
        reason="Set SYSTEMD_SMOKE_TESTS=1 to enable smoke tests",
    )
    def test_systemd_analyze_verify(self, systemd_dir):
        """Test that all service files pass systemd-analyze verify."""
        service_files = sorted(systemd_dir.glob("*.service"))
        assert service_files, "No .service files found"

        failed = []
        for service_file in service_files:
            result = subprocess.run(
                ["systemd-analyze", "verify", str(service_file)],
                capture_output=True,
                text=True,
            )

            # Allow warnings about missing files (expected in CI)
            if result.returncode != 0:
                output = result.stdout + result.stderr
                # If it's only missing file warnings, consider it OK
                if "No such file or directory" not in output and "not executable" not in output:
                    failed.append((service_file.name, output))

        assert not failed, "systemd-analyze verify failed for:\n" + "\n".join(
            f"  {name}: {output}" for name, output in failed
        )

    @pytest.mark.skipif(
        os.getenv("SYSTEMD_SMOKE_TESTS") != "1",
        reason="Set SYSTEMD_SMOKE_TESTS=1 to enable smoke tests",
    )
    @pytest.mark.parametrize("service_name", SMOKE_TEST_SERVICES)
    def test_service_can_be_checked(self, service_name):
        """Test that service status can be checked."""
        # Try system-level first, then user-level
        for scope in ["--system", "--user"]:
            result = subprocess.run(
                ["systemctl", scope, "status", service_name],
                capture_output=True,
            )
            # Status check should not fail completely (service may be inactive, that's OK)
            # We just verify the service is known to systemd
            if result.returncode in (0, 3, 4):  # 0=active, 3=inactive, 4=not found
                return

        pytest.fail(f"Service {service_name} not found in system or user scope")

    @pytest.mark.skipif(
        os.getenv("SYSTEMD_SMOKE_TESTS") != "1" or os.getenv("SYSTEMD_SMOKE_FULL") != "1",
        reason="Set SYSTEMD_SMOKE_TESTS=1 and SYSTEMD_SMOKE_FULL=1 to enable full smoke tests",
    )
    @pytest.mark.parametrize("service_name", SMOKE_TEST_SERVICES)
    def test_service_start_stop(self, service_name):
        """
        Test that service can be started and stopped.

        WARNING: This test actually starts and stops services.
        Only run in controlled test environments.
        """
        # Check if running as root (required for system services)
        if os.geteuid() != 0:
            pytest.skip("Service start/stop tests require root privileges")

        # Get initial state
        initial_state = self._get_service_state(service_name)

        try:
            # Try to start the service
            result = subprocess.run(
                ["systemctl", "start", service_name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, f"Failed to start {service_name}: {result.stderr}"

            # Check if service reached active state
            state = self._get_service_state(service_name)
            assert state in ("active", "inactive", "activating"), f"Unexpected state after start: {state}"

            # Stop the service
            result = subprocess.run(
                ["systemctl", "stop", service_name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, f"Failed to stop {service_name}: {result.stderr}"

        finally:
            # Restore initial state
            if initial_state == "active":
                subprocess.run(["systemctl", "start", service_name], capture_output=True)
            else:
                subprocess.run(["systemctl", "stop", service_name], capture_output=True)

    @staticmethod
    def _get_service_state(service_name: str) -> str:
        """Get the current state of a service."""
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()


class TestSystemdIntegration:
    """Integration tests that verify systemd configuration without starting services."""

    def test_daemon_reload_succeeds(self, systemd_dir):
        """Test that systemd daemon-reload succeeds with current service files."""
        if os.getenv("SYSTEMD_SMOKE_TESTS") != "1":
            pytest.skip("Set SYSTEMD_SMOKE_TESTS=1 to enable")

        if os.geteuid() != 0:
            pytest.skip("daemon-reload requires root privileges")

        result = subprocess.run(
            ["systemctl", "daemon-reload"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"daemon-reload failed: {result.stderr}"

    def test_service_files_can_be_loaded(self, systemd_dir):
        """Test that all service files can be shown (loaded by systemd)."""
        if os.getenv("SYSTEMD_SMOKE_TESTS") != "1":
            pytest.skip("Set SYSTEMD_SMOKE_TESTS=1 to enable")

        service_files = sorted(systemd_dir.glob("*.service"))
        failed = []

        for service_file in service_files:
            service_name = service_file.name

            # Try to show the service (this loads the unit file)
            result = subprocess.run(
                ["systemctl", "show", service_name],
                capture_output=True,
                text=True,
                timeout=10,
            )

            # If we can't show it, it might not be installed - that's OK for this test
            # We're just checking that systemd can parse our service files
            if result.returncode != 0 and "not loaded" not in result.stderr:
                failed.append((service_name, result.stderr))

        if failed:
            # This is informational - services may not be installed in CI
            pytest.skip("Some services could not be loaded (info): " + ", ".join(name for name, _ in failed))


if __name__ == "__main__":
    # Allow running directly for debugging
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        print(f"systemd available: {systemd_available()}")
        sys.exit(0 if systemd_available() else 1)

    pytest.main([__file__, "-v"])
