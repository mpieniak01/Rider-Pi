"""Tests for voice metrics module."""

from apps.voice.voice_metrics import VoiceMetrics


def test_voice_metrics_initialization():
    """Test VoiceMetrics initializes with zero values."""
    metrics = VoiceMetrics()

    assert metrics.audio_bytes_in == 0
    assert metrics.audio_bytes_out == 0
    assert metrics.audio_chunks_sent == 0
    assert metrics.audio_chunks_dropped == 0
    assert metrics.tts_bytes_received == 0
    assert metrics.tts_chunks_received == 0
    assert metrics.reconnects == 0


def test_audio_chunk_tracking():
    """Test audio chunk metrics are tracked correctly."""
    metrics = VoiceMetrics()

    metrics.on_audio_chunk(bytes_in=100, bytes_out=80)
    assert metrics.audio_bytes_in == 100
    assert metrics.audio_bytes_out == 80
    assert metrics.audio_chunks_sent == 1

    metrics.on_audio_chunk(bytes_in=150, bytes_out=120)
    assert metrics.audio_bytes_in == 250
    assert metrics.audio_bytes_out == 200
    assert metrics.audio_chunks_sent == 2


def test_audio_drop_tracking():
    """Test audio drop metrics are tracked correctly."""
    metrics = VoiceMetrics()

    metrics.on_audio_drop()
    assert metrics.audio_chunks_dropped == 1

    metrics.on_audio_drop(count=5)
    assert metrics.audio_chunks_dropped == 6


def test_tts_chunk_tracking():
    """Test TTS chunk metrics are tracked correctly."""
    metrics = VoiceMetrics()

    metrics.on_tts_chunk(bytes_received=200)
    assert metrics.tts_bytes_received == 200
    assert metrics.tts_chunks_received == 1

    metrics.on_tts_chunk(bytes_received=300)
    assert metrics.tts_bytes_received == 500
    assert metrics.tts_chunks_received == 2


def test_response_rtt_calculation():
    """Test response RTT is calculated correctly."""
    metrics = VoiceMetrics()

    metrics.on_commit()
    assert metrics.last_commit_ts is not None

    # Simulate small delay
    import time

    time.sleep(0.01)

    metrics.on_response()
    assert metrics.last_response_ts is not None
    assert metrics.response_rtt_ms is not None
    assert metrics.response_rtt_ms > 0


def test_connection_tracking():
    """Test connection metrics are tracked correctly."""
    metrics = VoiceMetrics()

    metrics.on_connect()
    assert metrics.connection_start_ts is not None

    import time

    time.sleep(0.01)

    metrics.on_disconnect()
    assert metrics.connection_start_ts is None
    assert metrics.connection_duration_s > 0


def test_reconnect_tracking():
    """Test reconnect counter increments correctly."""
    metrics = VoiceMetrics()

    assert metrics.reconnects == 0

    metrics.on_reconnect()
    assert metrics.reconnects == 1

    metrics.on_reconnect()
    assert metrics.reconnects == 2


def test_metrics_to_dict():
    """Test metrics can be exported to dict."""
    metrics = VoiceMetrics()

    metrics.on_audio_chunk(bytes_in=100, bytes_out=80)
    metrics.on_tts_chunk(bytes_received=200)
    metrics.on_reconnect()

    data = metrics.to_dict()

    assert isinstance(data, dict)
    assert data["audio_bytes_in"] == 100
    assert data["audio_bytes_out"] == 80
    assert data["audio_chunks_sent"] == 1
    assert data["tts_bytes_received"] == 200
    assert data["tts_chunks_received"] == 1
    assert data["reconnects"] == 1
    assert "uptime_s" in data


def test_metrics_reset():
    """Test metrics reset correctly."""
    metrics = VoiceMetrics()

    # Populate some data
    metrics.on_audio_chunk(bytes_in=100, bytes_out=80)
    metrics.on_tts_chunk(bytes_received=200)
    metrics.on_commit()
    metrics.on_response()

    # Reset
    metrics.reset()

    assert metrics.audio_bytes_in == 0
    assert metrics.audio_bytes_out == 0
    assert metrics.audio_chunks_sent == 0
    assert metrics.tts_bytes_received == 0
    assert metrics.tts_chunks_received == 0
    assert metrics.last_commit_ts is None
    assert metrics.last_response_ts is None
    assert metrics.response_rtt_ms is None
