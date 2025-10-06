# apps/voice/rt_protocol.py
"""
Realtime API protocol message builders and validators.

Extracted from stream_chunks.py (Issue mpieniak01/Rider-Pi#80 - PR-1 refactoring).
Provides functions to build and validate OpenAI Realtime API messages:
- session.update (with input_audio_format object)
- input_audio_buffer.append/commit
- response.create/cancel
- Message type constants and validation

NO API CHANGES - pure extraction of protocol layer.
"""

from __future__ import annotations

import base64
import json
from typing import Any


# ────────────────────────────────────────────────────────────────────────────
# Message type constants
# ────────────────────────────────────────────────────────────────────────────
class RealtimeMessageType:
    """Constants for Realtime API message types."""

    # Client -> Server
    SESSION_UPDATE = "session.update"
    INPUT_AUDIO_BUFFER_APPEND = "input_audio_buffer.append"
    INPUT_AUDIO_BUFFER_COMMIT = "input_audio_buffer.commit"
    INPUT_AUDIO_BUFFER_CLEAR = "input_audio_buffer.clear"
    RESPONSE_CREATE = "response.create"
    RESPONSE_CANCEL = "response.cancel"

    # Server -> Client
    SESSION_CREATED = "session.created"
    SESSION_UPDATED = "session.updated"
    RESPONSE_CREATED = "response.created"
    RESPONSE_DONE = "response.done"
    RESPONSE_AUDIO_DELTA = "response.audio.delta"
    RESPONSE_AUDIO_DONE = "response.audio.done"
    RESPONSE_OUTPUT_AUDIO_DELTA = "response.output_audio.delta"
    RESPONSE_TEXT_DELTA = "response.text.delta"
    ERROR = "error"
    RATE_LIMITS_UPDATED = "rate_limits.updated"


# ────────────────────────────────────────────────────────────────────────────
# Helper functions
# ────────────────────────────────────────────────────────────────────────────
def _get(src: Any, key: str, default: Any) -> Any:
    """Pobierz wartość z dict lub obiektu przez atrybut; w innym wypadku zwróć default."""
    try:
        if isinstance(src, dict):
            return src.get(key, default)
        if hasattr(src, key):
            return getattr(src, key)
    except Exception:
        pass
    return default


# ────────────────────────────────────────────────────────────────────────────
# Message builders
# ────────────────────────────────────────────────────────────────────────────
def build_session_update(
    *,
    voice: str = "verse",
    instructions: str = "",
    input_sample_rate: int = 16000,
    output_sample_rate: int = 16000,
    server_vad: bool = True,
    silence_duration_ms: int = 700,
    max_turn_duration_ms: int = 6000,
    temperature: float | None = None,
    modalities: list[str] | None = None,
) -> str:
    """Build session.update message with proper input_audio_format object.

    Args:
        voice: TTS voice to use (default: verse)
        instructions: System instructions for the session
        input_sample_rate: Input audio sample rate in Hz (default: 16000)
        output_sample_rate: Output audio sample rate in Hz (default: 16000)
        server_vad: Enable server-side VAD for turn detection (default: True)
        silence_duration_ms: Silence duration for turn detection (default: 700)
        max_turn_duration_ms: Maximum turn duration (default: 6000)
        temperature: Optional temperature for model responses
        modalities: List of modalities (default: ["text", "audio"])

    Returns:
        JSON string of session.update message
    """
    if modalities is None:
        modalities = ["text", "audio"]

    turn_detection: dict[str, Any] | None
    if server_vad:
        turn_detection = {
            "type": "server_vad",
            "silence_duration_ms": silence_duration_ms,
            "max_turn_duration_ms": max_turn_duration_ms,
        }
    else:
        turn_detection = None  # PTT/manual control

    session_update: dict[str, Any] = {
        "type": RealtimeMessageType.SESSION_UPDATE,
        "session": {
            "modalities": modalities,
            "voice": voice,
            "instructions": instructions,
            "turn_detection": turn_detection,
            "input_audio_format": {
                "type": "pcm16",
                "sample_rate_hz": input_sample_rate,
                "channels": 1,
            },
            "output_audio_format": {
                "type": "pcm16",
                "sample_rate_hz": output_sample_rate,
                "channels": 1,
            },
            "input_audio_transcription": {"model": "whisper-1"},
        },
    }

    if temperature is not None:
        try:
            session_update["session"]["temperature"] = float(temperature)
        except (ValueError, TypeError):
            pass

    return json.dumps(session_update)


def build_audio_append(audio_data: bytes) -> str:
    """Build input_audio_buffer.append message.

    Args:
        audio_data: Raw audio bytes to encode and append

    Returns:
        JSON string of input_audio_buffer.append message
    """
    audio_b64 = base64.b64encode(audio_data).decode("ascii")
    return json.dumps({
        "type": RealtimeMessageType.INPUT_AUDIO_BUFFER_APPEND,
        "audio": audio_b64,
    })


def build_audio_commit() -> str:
    """Build input_audio_buffer.commit message.

    Returns:
        JSON string of input_audio_buffer.commit message
    """
    return json.dumps({"type": RealtimeMessageType.INPUT_AUDIO_BUFFER_COMMIT})


def build_audio_clear() -> str:
    """Build input_audio_buffer.clear message.

    Returns:
        JSON string of input_audio_buffer.clear message
    """
    return json.dumps({"type": RealtimeMessageType.INPUT_AUDIO_BUFFER_CLEAR})


def build_response_create(
    *,
    voice: str = "verse",
    instructions: str = "Odpowiadaj krótko i po polsku.",
    modalities: list[str] | None = None,
    conversation: str = "default",
) -> str:
    """Build response.create message.

    Args:
        voice: TTS voice to use (default: verse)
        instructions: Response instructions (default: Polish short answers)
        modalities: List of modalities (default: ["text", "audio"])
        conversation: Conversation ID (default: "default")

    Returns:
        JSON string of response.create message
    """
    if modalities is None:
        modalities = ["text", "audio"]

    response_msg = {
        "type": RealtimeMessageType.RESPONSE_CREATE,
        "response": {
            "conversation": conversation,
            "instructions": instructions,
            "modalities": modalities,
            "audio": {"voice": voice},
        },
    }
    return json.dumps(response_msg)


def build_response_cancel() -> str:
    """Build response.cancel message for barge-in.

    Returns:
        JSON string of response.cancel message
    """
    return json.dumps({"type": RealtimeMessageType.RESPONSE_CANCEL})


# ────────────────────────────────────────────────────────────────────────────
# Message validators and parsers
# ────────────────────────────────────────────────────────────────────────────
def parse_message_type(message_json: str) -> str | None:
    """Parse message type from JSON string.

    Args:
        message_json: JSON message string

    Returns:
        Message type string or None if invalid
    """
    try:
        data = json.loads(message_json)
        msg_type = data.get("type")
        if isinstance(msg_type, str):
            return msg_type
    except Exception:
        pass
    return None


def decode_audio_from_message(message_data: dict[str, Any]) -> bytes | None:
    """Decode base64 audio data from WebSocket message (RT API variants).

    Args:
        message_data: Parsed message dict

    Returns:
        Decoded audio bytes or None if no audio found
    """
    try:
        msg_type = message_data.get("type")
        if msg_type == RealtimeMessageType.RESPONSE_AUDIO_DELTA:
            audio_b64 = message_data.get("delta", "")
            if audio_b64:
                return base64.b64decode(audio_b64)
        elif msg_type == "response.audio":
            audio_b64 = message_data.get("audio", "")
            if audio_b64:
                return base64.b64decode(audio_b64)
        elif msg_type == RealtimeMessageType.RESPONSE_OUTPUT_AUDIO_DELTA:
            # Some implementations have delta on top-level, others in data.delta
            audio_b64 = message_data.get("delta", "")
            if not audio_b64:
                audio_b64 = (message_data.get("data") or {}).get("delta", "")
            if audio_b64:
                return base64.b64decode(audio_b64)
    except Exception:
        pass
    return None


def is_session_event(msg_type: str) -> bool:
    """Check if message type is a session event.

    Args:
        msg_type: Message type string

    Returns:
        True if session event
    """
    return msg_type in (
        RealtimeMessageType.SESSION_CREATED,
        RealtimeMessageType.SESSION_UPDATED,
        RealtimeMessageType.SESSION_UPDATE,
    )


def is_response_event(msg_type: str) -> bool:
    """Check if message type is a response event.

    Args:
        msg_type: Message type string

    Returns:
        True if response event
    """
    return msg_type.startswith("response.")


def is_error_event(msg_type: str) -> bool:
    """Check if message type is an error event.

    Args:
        msg_type: Message type string

    Returns:
        True if error event
    """
    return msg_type == RealtimeMessageType.ERROR
