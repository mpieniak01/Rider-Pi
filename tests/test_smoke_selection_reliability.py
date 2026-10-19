"""Smoke selection is explicit and an unknown service never counts as known."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def smoke(monkeypatch):
    """Load the real smoke tests with every systemctl invocation mocked."""
    import subprocess

    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(subprocess, "run", run)
    path = Path(__file__).with_name("test_systemd_smoke.py")
    spec = importlib.util.spec_from_file_location("isolated_systemd_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run.reset_mock()
    return module, run


def test_empty_selection_produces_an_explicit_skip_without_commands(smoke):
    """Empty authorization keeps a named skipped case and performs no operation."""
    module, run = smoke
    cases = module.smoke_service_cases()
    assert len(cases) == 1
    assert cases[0].values == (None,)
    assert cases[0].id == "no-authorized-services"
    assert any(mark.name == "skip" for mark in cases[0].marks)
    run.assert_not_called()


def test_explicit_selection_is_preserved_without_commands(smoke, monkeypatch):
    """Selecting a dummy test name does not itself contact the service manager."""
    module, run = smoke
    monkeypatch.setattr(module, "SMOKE_TEST_SERVICES", ["isolated-dummy.service"])
    assert module.smoke_service_cases() == ["isolated-dummy.service"]
    run.assert_not_called()


@pytest.mark.parametrize("status", [0, 3])
def test_active_and_inactive_known_services_are_accepted(smoke, status):
    """Both active and inactive known units satisfy a status-only check."""
    module, run = smoke
    run.return_value = SimpleNamespace(returncode=status)
    module.TestSystemdSmoke().test_service_can_be_checked("isolated-dummy.service")
    assert run.call_count == 1


def test_unknown_service_fails_after_both_scopes(smoke):
    """The systemctl 'not found' exit code is not evidence of an installed unit."""
    module, run = smoke
    run.return_value = SimpleNamespace(returncode=4)
    check = module.TestSystemdSmoke()
    with pytest.raises(pytest.fail.Exception, match="not found"):
        check.test_service_can_be_checked("isolated-dummy.service")
    assert run.call_count == 2
    assert run.call_args_list[0].args[0][1] == "--system"
    assert run.call_args_list[1].args[0][1] == "--user"
