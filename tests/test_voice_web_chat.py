"""Tests for local LLM chat endpoint in apps.voice.web."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def app():
    """Create Flask app for testing."""
    from apps.voice.web import app

    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()


@pytest.fixture
def mock_config():
    """Mock configuration object."""
    config = MagicMock()
    config.chat.backend = "local"
    config.chat.system_prompt = "Test prompt"
    config.chat.llm_main_path = "/fake/llama.cpp/main"
    config.chat.llm_model_path = "/fake/model.gguf"
    config.chat.llm_extra_args = "-t 4 --simple-io"
    config.chat.timeout = 20.0
    return config


def test_api_chat_requires_local_backend(client, mock_config):
    """Test that /api/chat requires local backend configuration."""
    # Mock config with non-local backend
    mock_config.chat.backend = "openai"

    from apps.voice.web import app

    with app.app_context():
        with patch("apps.voice.web.g") as mock_g:
            mock_g.config = mock_config
            response = client.post(
                "/api/chat",
                data=json.dumps({"messages": [{"role": "user", "content": "test"}]}),
                content_type="application/json",
            )

    assert response.status_code == 500
    data = json.loads(response.data)
    assert data["ok"] is False
    assert "Lokalny backend czatu nie jest skonfigurowany." in data["error"]


def test_api_chat_checks_binary_exists(client, mock_config):
    """Test that /api/chat validates llama.cpp binary exists."""
    from apps.voice.web import app

    with app.app_context():
        with patch("apps.voice.web.g") as mock_g, patch("apps.voice.web.os.path.exists") as mock_exists:
            mock_g.config = mock_config
            # First call (binary check) returns False
            mock_exists.return_value = False

            response = client.post(
                "/api/chat",
                data=json.dumps({"messages": [{"role": "user", "content": "test"}]}),
                content_type="application/json",
            )

    assert response.status_code == 500
    data = json.loads(response.data)
    assert data["ok"] is False
    assert "Nie znaleziono binarki llama.cpp" in data["error"]


def test_api_chat_checks_model_exists(client, mock_config):
    """Test that /api/chat validates model file exists."""
    from apps.voice.web import app

    with app.app_context():
        with patch("apps.voice.web.g") as mock_g, patch("apps.voice.web.os.path.exists") as mock_exists:
            mock_g.config = mock_config
            # First call (binary) True, second call (model) False
            mock_exists.side_effect = [True, False]

            response = client.post(
                "/api/chat",
                data=json.dumps({"messages": [{"role": "user", "content": "test"}]}),
                content_type="application/json",
            )

    assert response.status_code == 500
    data = json.loads(response.data)
    assert data["ok"] is False
    assert "Nie znaleziono modelu LLM" in data["error"]


def test_api_chat_requires_messages(client, mock_config):
    """Test that /api/chat requires messages in payload."""
    from apps.voice.web import app

    with app.app_context():
        with patch("apps.voice.web.g") as mock_g, patch("apps.voice.web.os.path.exists") as mock_exists:
            mock_g.config = mock_config
            mock_exists.return_value = True

            response = client.post(
                "/api/chat",
                data=json.dumps({}),
                content_type="application/json",
            )

    assert response.status_code == 400
    data = json.loads(response.data)
    assert data["ok"] is False
    assert "Brak wiadomości" in data["error"]


def test_api_chat_successful_call(client, mock_config):
    """Test successful /api/chat call."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "This is a test response from llama.cpp"
    mock_result.stderr = ""

    from apps.voice.web import app

    with app.app_context():
        with (
            patch("apps.voice.web.g") as mock_g,
            patch("apps.voice.web.os.path.exists") as mock_exists,
            patch("apps.voice.web.subprocess.run") as mock_run,
        ):
            mock_g.config = mock_config
            mock_exists.return_value = True
            mock_run.return_value = mock_result

            response = client.post(
                "/api/chat",
                data=json.dumps({"messages": [{"role": "user", "content": "Hello"}]}),
                content_type="application/json",
            )

    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["ok"] is True
    assert data["text"] == "This is a test response from llama.cpp"
    assert data["message"]["role"] == "assistant"
    assert data["message"]["content"] == "This is a test response from llama.cpp"


def test_api_chat_handles_timeout(client, mock_config):
    """Test that /api/chat handles subprocess timeout."""
    from apps.voice.web import app

    with app.app_context():
        with (
            patch("apps.voice.web.g") as mock_g,
            patch("apps.voice.web.os.path.exists") as mock_exists,
            patch("apps.voice.web.subprocess.run") as mock_run,
        ):
            mock_g.config = mock_config
            mock_exists.return_value = True
            mock_run.side_effect = subprocess.TimeoutExpired("llama.cpp", 20.0)

            response = client.post(
                "/api/chat",
                data=json.dumps({"messages": [{"role": "user", "content": "Hello"}]}),
                content_type="application/json",
            )

    assert response.status_code == 504
    data = json.loads(response.data)
    assert data["ok"] is False
    assert "limit czasu" in data["error"]


def test_api_chat_handles_subprocess_error(client, mock_config):
    """Test that /api/chat handles subprocess errors."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "Some error from llama.cpp"

    from apps.voice.web import app

    with app.app_context():
        with (
            patch("apps.voice.web.g") as mock_g,
            patch("apps.voice.web.os.path.exists") as mock_exists,
            patch("apps.voice.web.subprocess.run") as mock_run,
        ):
            mock_g.config = mock_config
            mock_exists.return_value = True
            mock_run.return_value = mock_result

            response = client.post(
                "/api/chat",
                data=json.dumps({"messages": [{"role": "user", "content": "Hello"}]}),
                content_type="application/json",
            )

    assert response.status_code == 500
    data = json.loads(response.data)
    assert data["ok"] is False
    # Error message should not expose stderr for security
    assert "Błąd wykonania llama.cpp" in data["error"]
    assert "stderr" not in data  # Should not leak stderr to user


def test_api_chat_rejects_malicious_paths(client, mock_config):
    """Test that /api/chat rejects paths with shell metacharacters."""
    from apps.voice.web import app

    # Set malicious path with shell injection attempt
    mock_config.chat.llm_main_path = "/bin/sh;rm -rf /"

    with app.app_context():
        with patch("apps.voice.web.g") as mock_g:
            mock_g.config = mock_config

            response = client.post(
                "/api/chat",
                data=json.dumps({"messages": [{"role": "user", "content": "test"}]}),
                content_type="application/json",
            )

    assert response.status_code == 500
    data = json.loads(response.data)
    assert data["ok"] is False
    assert "Nieprawidłowa ścieżka" in data["error"]


def test_build_llama_prompt():
    """Test _build_llama_prompt helper function."""
    from apps.voice.web import _build_llama_prompt

    cfg = MagicMock()
    cfg.system_prompt = "You are a helpful assistant."

    messages = [
        {"role": "system", "content": "System message"},
        {"role": "user", "content": "Hello, world!"},
    ]

    prompt = _build_llama_prompt(cfg, messages)

    assert "<|system|>" in prompt
    assert "You are a helpful assistant." in prompt
    assert "<|user|>" in prompt
    assert "Hello, world!" in prompt
    assert "<|assistant|>" in prompt
    assert "<|end|>" in prompt
