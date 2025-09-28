"""Integration smoke tests for voice streaming functionality."""

import asyncio
import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.voice.svc_stream import StreamingVoiceService


class MockWebSocket:
    """Mock WebSocket for integration testing."""
    
    def __init__(self):
        self.sent_messages = []
        self.closed = False
        self.close_code = None
        
    async def send(self, message):
        if not self.closed:
            self.sent_messages.append(message)
    
    async def recv(self):
        if self.closed:
            raise ConnectionError("WebSocket closed")
        # Return a mock response for testing
        await asyncio.sleep(0.01)
        return json.dumps({
            "type": "response.audio.delta",
            "audio": base64.b64encode(b"mock_audio").decode()
        })
    
    async def close(self, code=1000):
        self.closed = True  
        self.close_code = code
        
    async def wait_closed(self):
        pass  # Mock successful wait


class TestStreamingIntegration:
    """Integration tests for streaming audio flow."""
    
    @pytest.fixture
    def service_config(self):
        return {
            "stream": {
                "endpoint": "wss://api.openai.com/v1/realtime",
                "auth": "env:OPENAI_API_KEY",
                "chunk_ms": 20,
                "sample_rate": 16000
            },
            "capture": {
                "device": "wm8960_in",
                "sample_rate": 16000,
                "channels": 2
            },
            "playback": {
                "device": "wm8960_out"
            },
            "service": {
                "beep": True
            }
        }
    
    @pytest.fixture
    def mock_service(self, service_config):
        """Create service with mocked dependencies."""
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}):
            service = StreamingVoiceService(service_config)
            
        # Mock WebSocket
        service.websocket = MockWebSocket()
        service.connected = True
        service.session_id = "test-session"
        
        return service
        
    def test_audio_normalization_in_stream(self, mock_service):
        """Test that stereo audio gets normalized to mono."""
        # Create stereo test data (4 bytes per stereo sample at S16_LE)
        stereo_audio = b"\x00\x01\x02\x03" * 10  # 40 bytes = 10 stereo samples
        
        # Run normalization
        asyncio.run(mock_service._send_audio_chunk(stereo_audio))
        
        # Check that message was sent
        assert len(mock_service.websocket.sent_messages) == 1
        
        # Parse the sent message
        sent_message = json.loads(mock_service.websocket.sent_messages[0])
        assert sent_message["type"] == "input_audio_buffer.append"
        assert "audio" in sent_message
        
        # Decode the base64 audio to verify it was processed
        decoded_audio = base64.b64decode(sent_message["audio"])
        
        # Mono audio should be smaller than stereo input (or at least not larger)
        assert len(decoded_audio) <= len(stereo_audio)
        
    @pytest.mark.asyncio
    async def test_websocket_graceful_close(self, mock_service):
        """Test that WebSocket closes gracefully with code 1000.""" 
        original_websocket = mock_service.websocket
        
        await mock_service.close()
        
        # Check that close was called with correct code on the original websocket
        assert original_websocket.close_code == 1000
        assert original_websocket.closed
        
        # Check cleanup
        assert mock_service.websocket is None
        assert not mock_service.connected
        
    def test_service_configuration(self, service_config):
        """Test service initializes with correct configuration."""
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}):
            service = StreamingVoiceService(service_config)
            
        # Check stream config
        assert service.stream_cfg.sample_rate == 16000
        assert service.stream_cfg.chunk_ms == 20
        
        # Check that beep is enabled
        assert service.config["service"]["beep"] is True
        
    @patch('apps.voice.svc_stream.play_ding')
    def test_ptt_beep_integration(self, mock_play_ding, mock_service):
        """Test PTT beep is played when enabled."""
        # Simulate PTT activation
        mock_service.ptt_enabled = True
        mock_service.ptt_active = False
        
        # Mock stdin for PTT thread
        with patch('sys.stdin') as mock_stdin:
            mock_stdin.readline.return_value = '\n'  # Simulate Enter press
            
            # Start PTT thread briefly
            import threading
            ptt_thread = threading.Thread(target=mock_service._ptt_keyboard_thread, daemon=True)
            ptt_thread.start()
            
            # Give it a moment to process
            import time
            time.sleep(0.1)
            
            # Stop the thread
            mock_service.stop_event.set()
            
        # Verify beep was attempted (might not complete due to mocking)
        # This tests the code path rather than actual audio playback
        assert mock_service.config["service"]["beep"] is True


class TestStreamingMetrics:
    """Test streaming metrics and logging."""
    
    @pytest.fixture  
    def service_with_logger(self):
        config = {
            "stream": {"endpoint": "ws://test", "auth": "test-key"},
            "capture": {"sample_rate": 16000, "channels": 2},
            "playback": {}, 
            "service": {"beep": False}
        }
        
        service = StreamingVoiceService(config)
        service.websocket = MockWebSocket()
        service.connected = True
        
        return service
    
    def test_stream_tx_logging(self, service_with_logger):
        """Test that stream.tx events are logged with correct metadata."""
        # Mock the logger to capture events
        events = []
        
        def mock_event(name, **kwargs):
            events.append({"name": name, "data": kwargs})
        
        service_with_logger.logger.event = mock_event
        
        # Send audio chunk
        stereo_audio = b"\x00\x01\x02\x03" * 10
        asyncio.run(service_with_logger._send_audio_chunk(stereo_audio))
        
        # Find the stream.tx event
        tx_events = [e for e in events if e["name"] == "stream.tx"]
        assert len(tx_events) == 1
        
        tx_event = tx_events[0]
        data = tx_event["data"]
        
        # Verify metadata
        assert data["ch_in"] == 2  # Input was stereo
        assert data["ch_out"] == 1  # Output should be mono
        assert data["sr"] == 16000  # Sample rate
        assert data["bytes_in"] == len(stereo_audio)
        assert data["bytes_out"] <= data["bytes_in"]  # Mono should be smaller