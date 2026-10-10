"""Core API and software tests remain usable without optional Google packages."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


def _fresh_module(monkeypatch):
    from services.api_core import google_home_api

    spec = importlib.util.spec_from_file_location("isolated_oauth", google_home_api.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def unavailable(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(module.importlib, "import_module", unavailable)
    return module


def test_api_import_without_google_packages():
    code = """
import sys
from importlib.abc import MetaPathFinder
from common.test_sandbox import install
install()
for name in list(sys.modules):
    if name == 'google' or name.startswith(('google.', 'google_auth_oauthlib')):
        del sys.modules[name]
class NoGoogle(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'google' or fullname.startswith(('google.', 'google_auth_oauthlib')):
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, NoGoogle())
from services.api_server import app
response = app.test_client().get('/healthz')
assert response.status_code == 200, response.data
assert not any(name == 'google' or name.startswith('google.') for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_configured_oauth_without_dependency_is_unavailable(monkeypatch):
    module = _fresh_module(monkeypatch)
    module.CLIENT_ID = "test-client"
    module.CLIENT_SECRET = "test-secret"
    expected = {"ok": False, "error": "oauth_dependency_unavailable"}
    assert module.build_auth_url_preview() == expected
    assert module.start_oauth_flow() == expected


def test_credentials_without_dependency_do_not_succeed(monkeypatch, tmp_path):
    module = _fresh_module(monkeypatch)
    module.TOKEN_FILE = tmp_path / "tokens.json"
    module.TOKEN_FILE.write_text(
        json.dumps({"refresh_token": "test", "token_uri": "test", "client_id": "test", "client_secret": "test"})
    )
    assert module._load_credentials() is None
    assert module.refresh_access_token() is None


def test_missing_configuration_still_requires_operator_setup(monkeypatch):
    module = _fresh_module(monkeypatch)
    module.CLIENT_ID = module.CLIENT_SECRET = ""
    with pytest.raises(ValueError, match="GOOGLE_CLIENT_ID"):
        module.start_oauth_flow()
    assert module.build_auth_url_preview()["error"] == "auth_env_missing"
