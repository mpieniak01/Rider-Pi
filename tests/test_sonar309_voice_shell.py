"""Execute only the shell harness's Python coroutine with inert service boundaries."""

from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def harness_main(namespace):
    path = ROOT / "scripts/sys_voice-stream.sh"
    embedded = path.read_text().split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
    tree = ast.parse(embedded, filename=str(path), feature_version=(3, 9))
    main = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "main")
    exec(compile(ast.Module(body=[main], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["main"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "configuration", "session", "response", "completion"])
async def test_shell_harness_uses_sync_configuration_and_always_cleans_started_session(monkeypatch, failure):
    service = SimpleNamespace(
        _initialize_transport=Mock(return_value=failure != "configuration"),
        _send_session_init=AsyncMock(),
        _session_prefs=SimpleNamespace(instructions=None),
        ptt_state=SimpleNamespace(start_interaction=Mock(), transition=Mock()),
        _message_handler_loop=AsyncMock(),
        _start_tts_player=Mock(),
        _send_response_create=AsyncMock(),
        _wait_for_completion=AsyncMock(),
        _cleanup=AsyncMock(),
    )
    for stage, member in [
        ("session", "_send_session_init"),
        ("response", "_send_response_create"),
        ("completion", "_wait_for_completion"),
    ]:
        if failure == stage:
            getattr(service, member).side_effect = RuntimeError("inert " + stage)
    construct = Mock(return_value=service)
    websocket_module = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "websockets", websocket_module)
    namespace = {
        "asyncio": asyncio,
        "StreamingVoiceService": construct,
        "cfg": {"inert": True},
        "prompt": "inert prompt",
        "PTTEvent": SimpleNamespace(START="inert start"),
    }
    main = harness_main(namespace)
    if failure == "configuration":
        with pytest.raises(SystemExit, match="Failed to initialize realtime transport"):
            await main()
        service._send_session_init.assert_not_awaited()
        service._cleanup.assert_not_awaited()
    elif failure is not None:
        with pytest.raises(RuntimeError, match="inert " + failure):
            await main()
        service._cleanup.assert_awaited_once_with()
    else:
        await main()
        service._cleanup.assert_awaited_once_with()
        service._send_response_create.assert_awaited_once_with()
        service._wait_for_completion.assert_awaited_once_with()
        assert service._session_prefs.instructions == "inert prompt"
    task = getattr(service, "_message_handler_task", None)
    if task is not None:
        await task
    construct.assert_called_once_with({"inert": True})
    service._initialize_transport.assert_called_once_with()
    assert service._ws_module is websocket_module
