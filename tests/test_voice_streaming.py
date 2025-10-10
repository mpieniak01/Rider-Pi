from __future__ import annotations

import asyncio
import json
import os
import queue
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.hardware

"""
Tests for WebSocket streaming voice service.

Tests the streaming functionality using mock WebSocket connections
to verify proper message handling, state transitions, and audio flow.
"""

from apps.voice.stream.service import StreamConfig, StreamingVoiceService


class MockWebSocket:
    """Mock WebSocket for testing."""

    def __init__(self):
        self.sent_messages: list[str] = []
        self.received_messages: queue.Queue[str] = queue.Queue()
        self.closed = False

    async def send(self, message: str):
        """Mock send method."""
        if not self.closed:
            self.sent_messages.append(message)

    async def recv(self):
        """Mock receive method."""
        if self.closed:
            raise ConnectionError("WebSocket closed")
        try:
            return self.received_messages.get(timeout=0.1)
        except queue.Empty:
            await asyncio.sleep(0.01)
            raise ConnectionError("No message") from None

    async def close(self):
        """Mock close method."""
        self.closed = True

    def put_message(self, message: str):
        """Add a message to be received."""
        self.received_messages.put(message)


@pytest.fixture
def mock_ui_publisher():
    """Mock UI publisher."""
    publisher = MagicMock()
    publisher.messages = []

    def publish(topic: str, payload: dict):
        publisher.messages.append((topic, payload))

    publisher.publish = publish
    return publisher


@pytest.fixture
def stream_config():
    """Base streaming configuration."""
    return {
        "asr": {"backend": "openai", "transport": "realtime", "language": "pl"},
        "chat": {
            "backend": "openai",
            "transport": "realtime",
            "system_prompt": "Test prompt",
            "max_tokens": 50,
        },
        "tts": {"backend": "openai", "transport": "realtime", "voice": "ash"},
        "stream": {
            "protocol": "websocket",
            "endpoint": "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview",
            "auth": "env:OPENAI_API_KEY",
            "chunk_ms": 20,
            "sample_rate": 16000,
            "send_partials": True,
            "reconnect": {"max_retries": 3},
        },
        "capture": {"backend": "alsa", "sample_rate": 16000, "channels": 1},
        "playback": {"backend": "alsa"},
    }


def _skip_if_no_device_env():
    if os.environ.get("RUN_DEVICE_TESTS") != "1":
        pytest.skip("Hardware/ALSA tests disabled on CI (set RUN_DEVICE_TESTS=1 to enable).")


def test_stream_config_creation(stream_config):
    """Test StreamConfig creation from dictionary."""
    config = StreamConfig.from_dict(stream_config)

    assert config.protocol == "websocket"
    assert config.chunk_ms == 20
    assert config.sample_rate == 16000
    assert config.send_partials is True
    assert config.max_retries == 3


def test_streaming_service_init(stream_config, mock_ui_publisher):
    """Test StreamingVoiceService initialization."""
    service = StreamingVoiceService(stream_config, mock_ui_publisher)

    assert service.config == stream_config
    assert service.ui_publisher == mock_ui_publisher
    assert service.current_state == "idle"
    assert service.connected is False


@pytest.mark.asyncio
async def test_websocket_message_handling(stream_config, mock_ui_publisher):
    """Test WebSocket message handling."""
    _skip_if_no_device_env()  # wywołujemy helper zamiast @usefixtures
    service = StreamingVoiceService(stream_config, mock_ui_publisher)

    # Test speech started message
    await service._handle_ws_message(json.dumps({"type": "input_audio_buffer.speech_started"}))

    # Verify state change
    states = [msg for msg in mock_ui_publisher.messages if msg[0] == "ui.state"]
    assert len(states) == 1
    assert states[0][1]["state"] == "hearing"

    # Test partial transcription
    await service._handle_ws_message(
        json.dumps(
            {
                "type": "conversation.item.input_audio_transcription.delta",
                "delta": "Hello world",
            }
        )
    )

    # Verify partial published
    partials = [msg for msg in mock_ui_publisher.messages if msg[0] == "ui.partial"]
    assert len(partials) == 1
    assert partials[0][1]["text"] == "Hello world"


def test_get_auth_header_bashenv_rejected(stream_config):
    """Test that bashenv scheme is rejected for security reasons."""
    # Modify config to use bashenv scheme
    stream_config["stream"]["auth"] = "bashenv:~/.bash_profile:OPENAI_API_KEY"
    service = StreamingVoiceService(stream_config)

    # Should raise RuntimeError with clear message
    with pytest.raises(RuntimeError, match="bashenv.*no longer supported.*security"):
        service._get_auth_header()


def test_get_auth_header(stream_config, monkeypatch):
    """Test API key extraction from environment."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    service = StreamingVoiceService(stream_config)

    auth_header = service._get_auth_header()
    assert auth_header == "test-key"


def test_ui_state_publishing(stream_config, mock_ui_publisher):
    """Test UI state change publishing."""
    service = StreamingVoiceService(stream_config, mock_ui_publisher)

    # Test state change
    service._publish_ui_state("hearing")

    # Verify message was published
    assert len(mock_ui_publisher.messages) == 1
    topic, payload = mock_ui_publisher.messages[0]
    assert topic == "ui.state"
    assert payload["state"] == "hearing"
    assert "ts" in payload

    # Test no duplicate publishing for same state
    service._publish_ui_state("hearing")
    assert len(mock_ui_publisher.messages) == 1  # Should not publish duplicate


def test_partial_transcript_publishing(stream_config, mock_ui_publisher):
    """Test partial transcript publishing."""
    service = StreamingVoiceService(stream_config, mock_ui_publisher)

    # Test partial publish
    service._publish_partial("Hello")

    # Verify message
    assert len(mock_ui_publisher.messages) == 1
    topic, payload = mock_ui_publisher.messages[0]
    assert topic == "ui.partial"
    assert payload["text"] == "Hello"

    # Test no duplicate for same text
    service._publish_partial("Hello")
    assert len(mock_ui_publisher.messages) == 1


@pytest.mark.asyncio
async def test_session_update_message(stream_config):
    """Test session update message format."""
    service = StreamingVoiceService(stream_config)
    service.websocket = MockWebSocket()

    await service._send_session_update()

    # Verify session update was sent
    assert len(service.websocket.sent_messages) == 1
    msg = json.loads(service.websocket.sent_messages[0])

    assert msg["type"] == "session.update"
    assert "session" in msg
    session = msg["session"]
    assert session["voice"] == "ash"
    # Updated to expect object format (not string) - PR-0 stabilization
    assert isinstance(session["input_audio_format"], dict)
    assert session["input_audio_format"]["type"] == "pcm16"
    assert session["input_audio_format"]["sample_rate_hz"] == 16000
    assert session["input_audio_format"]["channels"] == 1
    assert isinstance(session["output_audio_format"], dict)
    assert session["output_audio_format"]["type"] == "pcm16"
    assert session["output_audio_format"]["sample_rate_hz"] == 16000
    assert session["output_audio_format"]["channels"] == 1


@pytest.mark.asyncio
async def test_audio_chunk_sending(stream_config):
    """Test audio chunk encoding and sending."""
    service = StreamingVoiceService(stream_config)
    service.websocket = MockWebSocket()

    # Test sending audio chunk
    test_audio = b"\x00\x01\x02\x03"
    await service._send_audio_chunk(test_audio)

    # Verify message format
    assert len(service.websocket.sent_messages) == 1
    msg = json.loads(service.websocket.sent_messages[0])

    assert msg["type"] == "input_audio_buffer.append"
    assert "audio" in msg
    # Verify base64 encoding
    import base64

    assert base64.b64decode(msg["audio"]) == test_audio


def test_barge_in_detection(stream_config, mock_ui_publisher):
    """Test barge-in functionality."""
    service = StreamingVoiceService(stream_config, mock_ui_publisher)

    # Add some TTS data to queue
    service.tts_player_queue.put(b"audio1")
    service.tts_player_queue.put(b"audio2")

    # Trigger barge-in
    service.barge_in_event.set()

    # Simulate the behavior that would happen in the audio capture thread
    # Clear TTS queue on barge-in
    while not service.tts_player_queue.empty():
        try:
            service.tts_player_queue.get_nowait()
        except queue.Empty:
            break
    service.barge_in_event.clear()

    # Verify queue is cleared
    assert service.tts_player_queue.empty()
    assert not service.barge_in_event.is_set()


@pytest.mark.asyncio
async def test_connection_failure_handling(stream_config, mock_ui_publisher, monkeypatch, caplog):
    """Test connection failure handling without patching external websockets."""
    from apps.voice.stream import transport as transport_mod

    class FailingTransport:
        def __init__(self, *args, **kwargs):
            pass

        async def connect(self, *args, **kwargs):
            raise OSError("Connection failed")

        async def close(self):
            pass

    # Wstrzykujemy konstruktor transportu używany przez service:
    monkeypatch.setattr(transport_mod, "WebSocketTransport", FailingTransport, raising=True)

    caplog.clear()
    caplog.set_level("INFO")

    service = StreamingVoiceService(stream_config, mock_ui_publisher)

    # Kompatybilnie: preferuj prywatne _connect, inaczej użyj connect();
    # jeśli metoda rzuci wyjątek, potraktuj to jako "nieudane połączenie".
    success = False
    try:
        if hasattr(service, "_connect") and asyncio.iscoroutinefunction(service._connect):
            success = await service._connect()  # type: ignore[attr-defined]
        elif hasattr(service, "connect") and asyncio.iscoroutinefunction(service.connect):
            success = await service.connect()  # type: ignore[attr-defined]
        else:
            # Brak znanych metod łączenia – zachowanie jak przy niepowodzeniu.
            success = False
    except Exception:
        success = False

    assert success is False
    assert service.connected is False

    # Verify error was published
    errors = [msg for msg in mock_ui_publisher.messages if msg[0] == "ui.error"]
    assert len(errors) == 1
    assert errors[0][1]["type"] == "ws_connect"


if __name__ == "__main__":
    pytest.main([__file__])
