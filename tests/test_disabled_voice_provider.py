"""Removed cloud SDK selections must fail before I/O or conversation changes."""

from __future__ import annotations

import pytest

from apps.voice.asr import ASRConfig, ASRError, transcribe
from apps.voice.chat import ChatConfig, ChatError, ChatSession
from apps.voice.config_loader import ValidationError, _normalize_backends
from apps.voice.tts import TTSConfig, TTSError, synthesize


@pytest.mark.parametrize("backend", ["google", "gemini"])
def test_removed_voice_backend_is_rejected_without_changing_chat_history(backend):
    with pytest.raises(ASRError, match="SDK integration is disabled"):
        transcribe(b"\0\0", 16000, ASRConfig(backend=backend))
    with pytest.raises(TTSError, match="SDK integration is disabled"):
        synthesize("fixture", TTSConfig(backend=backend))
    session = ChatSession(ChatConfig(backend=backend, model="", system_prompt=""))
    with pytest.raises(ChatError, match="SDK integration is disabled"):
        session.ask("fixture")
    assert session._history == []
    for section in ["asr", "chat", "tts"]:
        with pytest.raises(ValidationError, match="SDK integration is disabled"):
            _normalize_backends({section: {"backend": backend}})


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["google", "gemini"])
async def test_removed_streaming_backend_has_no_history_side_effect(backend):
    session = ChatSession(ChatConfig(backend=backend, model="", system_prompt="", transport="realtime"))
    with pytest.raises(ChatError, match="SDK integration is disabled"):
        async for _ in session.ask_stream("fixture"):
            pytest.fail("Disabled provider emitted output")
    assert session._history == []
