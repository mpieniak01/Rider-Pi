# apps/voice/tests/test_stream_chunks.py
import base64
import json

from apps.voice import voice_logging
from apps.voice.audio.capture import CaptureConfig
from apps.voice.stream_chunks import AudioChunkProcessor, calculate_chunk_size, decode_audio_from_message


class DummyLogger:
    def event(self, *a, **k):
        pass


def test_calculate_chunk_size():
    # 16kHz * 20ms * 2B = 640B
    assert calculate_chunk_size(16000, 20) == 640


def test_process_and_encode_chunk():
    cfg = CaptureConfig(
        backend="alsa",
        device="hw:0,0",
        sample_rate=16000,
        channels=1,
        frame_ms=20,
        buffer_seconds=0.1,
        sample_format="S16_LE",
    )
    proc = AudioChunkProcessor(cfg, stream_cfg=type("SC", (), {"chunk_ms": 20})(), logger=DummyLogger())
    raw = b"\x00\x00" * 320  # 320 sampli = 20ms @16kHz mono (2B/sample)
    msg, telemetry = proc.process_and_encode_chunk(raw)
    obj = json.loads(msg)
    assert obj["type"] == "input_audio_buffer.append"
    assert isinstance(obj["audio"], str)
    assert telemetry["bytes_in"] == 640
    assert telemetry["bytes_out"] == 640
    # roundtrip dekodowania
    decoded = base64.b64decode(obj["audio"])
    assert decoded == raw


def test_decode_audio_from_message():
    pcm = b"\x01\x02" * 10
    b64 = base64.b64encode(pcm).decode("utf-8")
    for payload in [
        {"type": "response.audio.delta", "delta": b64},
        {"type": "response.audio", "audio": b64},
        {"type": "response.output_audio.delta", "delta": b64},
        {"type": "response.output_audio.delta", "data": {"delta": b64}},
    ]:
        out = decode_audio_from_message(payload)
        assert out == pcm
