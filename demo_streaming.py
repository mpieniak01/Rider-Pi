# ruff: noqa: E402
#!/usr/bin/env python3
"""
Manual demo of the streaming voice service functionality.

This script demonstrates the streaming mode detection and configuration
without requiring an actual OpenAI API key or WebSocket connection.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, project_root)

from apps.voice import config as voice_config
from apps.voice.stream.service import StreamConfig, StreamingVoiceService
from apps.voice.svc_core import _wants_stream


def demo_config_loading():
    """Demonstrate configuration loading and streaming detection."""
    print("=" * 60)
    print("STREAMING VOICE SERVICE DEMO")
    print("=" * 60)

    # Test file-based config
    print("\n1. File-based configuration (config/voice.toml):")
    try:
        cfg_file = voice_config.load("config/voice.toml")
        is_streaming = _wants_stream(cfg_file, None)
        print(f"   Mode: {'Streaming' if is_streaming else 'File-based'}")
        print(f"   ASR transport: {cfg_file['asr'].get('transport', 'default')}")
        print(f"   Chat transport: {cfg_file['chat'].get('transport', 'default')}")
        print(f"   TTS transport: {cfg_file['tts'].get('transport', 'default')}")
    except Exception as e:
        print(f"   Error loading file config: {e}")

    # Test streaming config
    print("\n2. Streaming configuration (config/voice_streaming.toml):")
    try:
        cfg_stream = voice_config.load("config/voice_streaming.toml")
        is_streaming = _wants_stream(cfg_stream, None)
        print(f"   Mode: {'Streaming' if is_streaming else 'File-based'}")
        print(f"   ASR transport: {cfg_stream['asr'].get('transport', 'default')}")
        print(f"   Chat transport: {cfg_stream['chat'].get('transport', 'default')}")
        print(f"   TTS transport: {cfg_stream['tts'].get('transport', 'default')}")
        print(f"   Stream protocol: {cfg_stream.get('stream', {}).get('protocol', 'none')}")
        print(f"   Stream endpoint: {cfg_stream.get('stream', {}).get('endpoint', 'none')[:50]}...")
    except Exception as e:
        print(f"   Error loading streaming config: {e}")


def demo_stream_config():
    """Demonstrate StreamConfig creation and parsing."""
    print("\n3. StreamConfig parsing:")

    sample_config = {
        "stream": {
            "protocol": "websocket",
            "endpoint": "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview",
            "auth": "env:OPENAI_API_KEY",
            "chunk_ms": 20,
            "sample_rate": 16000,
            "send_partials": True,
            "reconnect": {"max_retries": 5, "base_ms": 250},
            "audio": {"jitter_buffer_ms": 150, "barge_in": True},
        }
    }

    stream_cfg = StreamConfig.from_dict(sample_config)
    print(f"   Protocol: {stream_cfg.protocol}")
    print(f"   Chunk size: {stream_cfg.chunk_ms}ms")
    print(f"   Sample rate: {stream_cfg.sample_rate}Hz")
    print(f"   Partial results: {stream_cfg.send_partials}")
    print(f"   Max retries: {stream_cfg.max_retries}")
    print(f"   Jitter buffer: {stream_cfg.jitter_buffer_ms}ms")
    print(f"   Barge-in enabled: {stream_cfg.barge_in}")


def demo_service_creation():
    """Demonstrate StreamingVoiceService creation."""
    print("\n4. StreamingVoiceService creation:")

    sample_config = {
        "asr": {"backend": "openai", "transport": "realtime"},
        "chat": {"backend": "openai", "transport": "realtime"},
        "tts": {"backend": "openai", "transport": "realtime"},
        "stream": {
            "protocol": "websocket",
            "endpoint": "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview",
            "auth": "env:OPENAI_API_KEY",
            "chunk_ms": 20,
        },
        "capture": {"backend": "alsa", "sample_rate": 16000},
        "playback": {"backend": "alsa"},
    }

    try:
        service = StreamingVoiceService(sample_config)
        print("   Service created successfully")
        print(f"   Current state: {service.current_state}")
        print(f"   Connected: {service.connected}")
        print(f"   Stream endpoint: {service.stream_cfg.endpoint[:50]}...")
        print(f"   Auth method: {service.stream_cfg.auth}")
    except Exception as e:
        print(f"   Error creating service: {e}")


def demo_ui_events():
    """Demonstrate UI event publishing."""
    print("\n5. UI Event publishing:")

    class MockPublisher:
        def __init__(self):
            self.messages = []

        def publish(self, topic, payload):
            self.messages.append((topic, payload))
            print(f"   Published: {topic} -> {payload}")

    sample_config = {
        "asr": {"backend": "openai", "transport": "realtime"},
        "chat": {"backend": "openai", "transport": "realtime"},
        "tts": {"backend": "openai", "transport": "realtime"},
        "stream": {"protocol": "websocket", "auth": "env:TEST_KEY"},
        "capture": {"backend": "alsa"},
        "playback": {"backend": "alsa"},
    }

    publisher = MockPublisher()
    service = StreamingVoiceService(sample_config, publisher)

    # Test state transitions
    service._publish_ui_state("hearing")
    service._publish_ui_state("thinking")
    service._publish_partial("Hello world")
    service._publish_ui_state("speaking")

    print(f"   Total messages published: {len(publisher.messages)}")


def main():
    """Run the demo."""
    try:
        demo_config_loading()
        demo_stream_config()
        demo_service_creation()
        demo_ui_events()

        print("\n" + "=" * 60)
        print("DEMO COMPLETED SUCCESSFULLY")
        print("=" * 60)
        print("\nTo test with real OpenAI API:")
        print("1. Set OPENAI_API_KEY environment variable")
        print("2. Run: python -m apps.voice.cli --config config/voice_streaming.toml listen")
        print("\nFor file-based mode (no API key needed):")
        print("   Run: python -m apps.voice.cli --config config/voice.toml diag")

    except Exception as e:
        print(f"\nDemo failed: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
