"""Tests for audio TX and RX modules."""

import queue
import threading
from unittest.mock import MagicMock, Mock

from apps.voice.audio_rx_tts import AudioReceiver
from apps.voice.audio_tx import AudioTransmitter


def test_audio_transmitter_initialization():
    """Test AudioTransmitter initializes correctly."""
    config = {"capture": {"sample_rate": 16000}}
    stream_cfg = Mock(chunk_ms=20)
    audio_queue = queue.Queue()
    logger = MagicMock()
    stop_event = threading.Event()

    transmitter = AudioTransmitter(
        config=config,
        stream_cfg=stream_cfg,
        audio_queue=audio_queue,
        logger=logger,
        stop_event=stop_event,
        ptt_enabled=False,
    )

    assert transmitter.config == config
    assert transmitter.stream_cfg == stream_cfg
    assert transmitter.audio_queue == audio_queue
    assert transmitter.logger == logger
    assert transmitter.stop_event == stop_event
    assert transmitter.ptt_enabled is False
    assert transmitter.ptt_active is False
    assert transmitter.connected is False


def test_audio_transmitter_state_tracking():
    """Test AudioTransmitter state tracking."""
    config = {"capture": {"sample_rate": 16000}}
    stream_cfg = Mock(chunk_ms=20)
    audio_queue = queue.Queue()
    logger = MagicMock()
    stop_event = threading.Event()

    transmitter = AudioTransmitter(
        config=config,
        stream_cfg=stream_cfg,
        audio_queue=audio_queue,
        logger=logger,
        stop_event=stop_event,
        ptt_enabled=True,
    )

    assert transmitter._any_audio_since_commit is False

    transmitter._any_audio_since_commit = True
    assert transmitter._any_audio_since_commit is True


def test_audio_receiver_initialization():
    """Test AudioReceiver initializes correctly."""
    config = {"playback": {"backend": "alsa"}}
    stream_cfg = Mock(jitter_buffer_ms=100)
    tts_queue = queue.Queue()
    logger = MagicMock()
    stop_event = threading.Event()
    barge_in_event = threading.Event()

    receiver = AudioReceiver(
        config=config,
        stream_cfg=stream_cfg,
        tts_queue=tts_queue,
        logger=logger,
        stop_event=stop_event,
        barge_in_event=barge_in_event,
    )

    assert receiver.config == config
    assert receiver.stream_cfg == stream_cfg
    assert receiver.tts_queue == tts_queue
    assert receiver.logger == logger
    assert receiver.stop_event == stop_event
    assert receiver.barge_in_event == barge_in_event


def test_audio_receiver_callbacks():
    """Test AudioReceiver callback setup."""
    config = {"playback": {"backend": "alsa"}}
    stream_cfg = Mock(jitter_buffer_ms=100)
    tts_queue = queue.Queue()
    logger = MagicMock()
    stop_event = threading.Event()
    barge_in_event = threading.Event()

    receiver = AudioReceiver(
        config=config,
        stream_cfg=stream_cfg,
        tts_queue=tts_queue,
        logger=logger,
        stop_event=stop_event,
        barge_in_event=barge_in_event,
    )

    # Test callback assignment
    callback_called = []

    def on_start():
        callback_called.append("start")

    def on_end():
        callback_called.append("end")

    receiver.on_playback_start = on_start
    receiver.on_playback_end = on_end

    # Verify callbacks can be called
    receiver.on_playback_start()
    receiver.on_playback_end()

    assert callback_called == ["start", "end"]


def test_audio_transmitter_callbacks():
    """Test AudioTransmitter callback setup."""
    config = {"capture": {"sample_rate": 16000}}
    stream_cfg = Mock(chunk_ms=20)
    audio_queue = queue.Queue()
    logger = MagicMock()
    stop_event = threading.Event()

    transmitter = AudioTransmitter(
        config=config,
        stream_cfg=stream_cfg,
        audio_queue=audio_queue,
        logger=logger,
        stop_event=stop_event,
        ptt_enabled=True,
    )

    # Test callback assignment
    callback_called = []

    def on_commit():
        callback_called.append("commit")

    def on_barge_in():
        callback_called.append("barge_in")

    transmitter.on_ptt_commit = on_commit
    transmitter.on_barge_in = on_barge_in

    # Verify callbacks can be called
    transmitter.on_ptt_commit()
    transmitter.on_barge_in()

    assert callback_called == ["commit", "barge_in"]
