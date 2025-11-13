"""Tests for AI mode API endpoints and configuration."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def reset_ai_mode():
    """Reset AI mode to default state before each test."""
    from common import ai_mode

    ai_mode._current_mode = "local"
    ai_mode._mode_changed_ts = time.time()
    yield
    ai_mode._current_mode = "local"
    ai_mode._mode_changed_ts = time.time()


def test_ai_mode_get_default(reset_ai_mode):
    """Test getting default AI mode."""
    from common.ai_mode import get_mode

    mode = get_mode()
    assert mode == "local"


def test_ai_mode_set_local(reset_ai_mode):
    """Test setting AI mode to local."""
    from common.ai_mode import get_mode, set_mode

    changed = set_mode("local")
    assert changed is False  # Already local
    assert get_mode() == "local"


def test_ai_mode_set_offload(reset_ai_mode):
    """Test setting AI mode to pc_offload."""
    from common.ai_mode import get_mode, set_mode

    changed = set_mode("pc_offload")
    assert changed is True
    assert get_mode() == "pc_offload"


def test_ai_mode_set_invalid(reset_ai_mode):
    """Test setting invalid AI mode."""
    from common.ai_mode import set_mode

    with pytest.raises(ValueError, match="Invalid AI mode"):
        set_mode("invalid")


def test_ai_mode_get_info(reset_ai_mode):
    """Test getting AI mode info with timestamp."""
    from common.ai_mode import get_mode_info, set_mode

    # Get initial info
    info1 = get_mode_info()
    assert info1["mode"] == "local"
    assert "changed_ts" in info1
    ts1 = info1["changed_ts"]

    # Change mode
    time.sleep(0.01)
    set_mode("pc_offload")

    # Get new info
    info2 = get_mode_info()
    assert info2["mode"] == "pc_offload"
    assert info2["changed_ts"] > ts1


def test_ai_mode_is_local(reset_ai_mode):
    """Test is_local helper function."""
    from common.ai_mode import is_local, set_mode

    assert is_local() is True
    set_mode("pc_offload")
    assert is_local() is False


def test_ai_mode_is_offload(reset_ai_mode):
    """Test is_offload helper function."""
    from common.ai_mode import is_offload, set_mode

    assert is_offload() is False
    set_mode("pc_offload")
    assert is_offload() is True


def test_ai_mode_api_get(reset_ai_mode):
    """Test GET /api/system/ai-mode endpoint."""
    from flask import Flask

    from services.api_core.ai_mode_api import get_ai_mode

    app = Flask(__name__)
    with app.test_request_context("/api/system/ai-mode", method="GET"):
        resp, status = get_ai_mode()
        assert status == 200
        data = json.loads(resp.get_data(as_text=True))
        assert data["mode"] == "local"
        assert "changed_ts" in data


def test_ai_mode_api_set_local(reset_ai_mode):
    """Test PUT /api/system/ai-mode endpoint with local mode."""
    from flask import Flask

    from services.api_core.ai_mode_api import set_ai_mode

    app = Flask(__name__)
    with app.test_request_context("/api/system/ai-mode", method="PUT", json={"mode": "local"}):
        resp, status = set_ai_mode()
        assert status == 200
        data = json.loads(resp.get_data(as_text=True))
        assert data["mode"] == "local"
        assert "changed" in data
        assert "changed_ts" in data


def test_ai_mode_api_set_offload(reset_ai_mode):
    """Test PUT /api/system/ai-mode endpoint with pc_offload mode."""
    from flask import Flask

    from services.api_core.ai_mode_api import set_ai_mode

    app = Flask(__name__)
    with app.test_request_context("/api/system/ai-mode", method="PUT", json={"mode": "pc_offload"}):
        resp, status = set_ai_mode()
        assert status == 200
        data = json.loads(resp.get_data(as_text=True))
        assert data["mode"] == "pc_offload"
        assert data["changed"] is True
        assert "changed_ts" in data


def test_ai_mode_api_set_invalid(reset_ai_mode):
    """Test PUT /api/system/ai-mode endpoint with invalid mode."""
    from flask import Flask

    from services.api_core.ai_mode_api import set_ai_mode

    app = Flask(__name__)
    with app.test_request_context("/api/system/ai-mode", method="PUT", json={"mode": "invalid"}):
        resp, status = set_ai_mode()
        assert status == 400
        data = json.loads(resp.get_data(as_text=True))
        assert "error" in data


def test_ai_mode_api_set_missing_mode(reset_ai_mode):
    """Test PUT /api/system/ai-mode endpoint without mode parameter."""
    from flask import Flask

    from services.api_core.ai_mode_api import set_ai_mode

    app = Flask(__name__)
    with app.test_request_context("/api/system/ai-mode", method="PUT", json={}):
        resp, status = set_ai_mode()
        assert status == 400
        data = json.loads(resp.get_data(as_text=True))
        assert "error" in data
        assert "Missing 'mode' parameter" in data["error"]


@patch("common.bus.BusPub")
def test_ai_mode_api_publishes_zmq_event(mock_publisher_cls, reset_ai_mode):
    """Test that changing AI mode publishes ZMQ event."""
    from flask import Flask

    from services.api_core.ai_mode_api import set_ai_mode

    # Create mock publisher instance
    mock_pub = MagicMock()
    mock_publisher_cls.return_value = mock_pub

    app = Flask(__name__)
    with app.test_request_context("/api/system/ai-mode", method="PUT", json={"mode": "pc_offload"}):
        resp, status = set_ai_mode()
        assert status == 200

        # Verify ZMQ event was published
        mock_pub.send.assert_called_once()
        call_args = mock_pub.send.call_args[0]
        assert call_args[0] == "system.ai.mode.changed"

        payload = call_args[1]
        assert payload["mode"] == "pc_offload"
        assert "ts" in payload

        # Verify publisher was closed
        mock_pub.close.assert_called_once()


def test_ai_mode_env_variable(reset_ai_mode):
    """Test that RIDER_AI_MODE environment variable is read."""
    from common import ai_mode

    with patch.dict("os.environ", {"RIDER_AI_MODE": "pc_offload"}):
        mode = ai_mode._read_env_mode()
        assert mode == "pc_offload"

    with patch.dict("os.environ", {"RIDER_AI_MODE": "local"}):
        mode = ai_mode._read_env_mode()
        assert mode == "local"

    with patch.dict("os.environ", {"RIDER_AI_MODE": "invalid"}):
        mode = ai_mode._read_env_mode()
        assert mode == "local"  # Falls back to default


def test_ai_mode_thread_safety(reset_ai_mode):
    """Test that AI mode operations are thread-safe."""
    import threading

    from common.ai_mode import get_mode, set_mode

    results = []
    errors = []

    def worker(mode):
        try:
            for _ in range(10):
                set_mode(mode)
                current = get_mode()
                results.append(current)
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=worker, args=("local",)),
        threading.Thread(target=worker, args=("pc_offload",)),
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    # No errors should occur
    assert len(errors) == 0

    # Final mode should be one of the valid modes
    final_mode = get_mode()
    assert final_mode in ("local", "pc_offload")
