"""Tests for Google Gemini ASR and TTS integration."""

from __future__ import annotations

import array
import io
import os
import wave
from unittest.mock import MagicMock, patch

import pytest

from apps.voice import voice_logging
from apps.voice.asr import ASRConfig, ASRError, transcribe
from apps.voice.tts import TTSConfig, TTSError, synthesize


def _make_test_wav(sample_rate: int = 16000, duration_s: float = 1.0) -> bytes:
    """Create a simple test WAV file."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        # Simple sine wave
        samples = array.array("h", [0] * int(sample_rate * duration_s))
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


@pytest.fixture(autouse=True)
def setup_logging():
    """Setup logging for tests."""
    voice_logging.configure()


class TestGeminiASR:
    """Tests for Gemini ASR backend."""

    def test_gemini_asr_requires_api_key(self):
        """Test that Gemini ASR requires GOOGLE_API_KEY."""
        config = ASRConfig(backend="google", model="gemini-1.5-flash")
        audio = _make_test_wav()

        # Remove GOOGLE_API_KEY if it exists
        old_key = os.environ.pop("GOOGLE_API_KEY", None)
        try:
            with pytest.raises(ASRError, match="GOOGLE_API_KEY not configured"):
                transcribe(audio, 16000, config)
        finally:
            if old_key:
                os.environ["GOOGLE_API_KEY"] = old_key

    def test_gemini_asr_requires_sdk(self):
        """Test that Gemini ASR requires google-generativeai SDK."""
        config = ASRConfig(backend="google", model="gemini-1.5-flash")
        audio = _make_test_wav()

        # Set a fake API key
        os.environ["GOOGLE_API_KEY"] = "fake-key-for-test"

        with patch.dict("sys.modules", {"google.generativeai": None}):
            with pytest.raises(ASRError, match="Google Generative AI SDK unavailable"):
                transcribe(audio, 16000, config)

    @patch("google.generativeai.GenerativeModel")
    @patch("google.generativeai.configure")
    def test_gemini_asr_success(self, mock_configure, mock_model_class):
        """Test successful Gemini ASR transcription."""
        # Setup mock
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Hello, this is a test"
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        config = ASRConfig(backend="google", model="gemini-1.5-flash", language="en")
        audio = _make_test_wav()

        os.environ["GOOGLE_API_KEY"] = "fake-key-for-test"

        result = transcribe(audio, 16000, config)

        assert result.text == "Hello, this is a test"
        assert result.language == "en"
        mock_configure.assert_called_once_with(api_key="fake-key-for-test")
        mock_model_class.assert_called_once_with(model_name="gemini-1.5-flash")

    @patch("google.generativeai.GenerativeModel")
    @patch("google.generativeai.configure")
    def test_gemini_asr_handles_errors(self, mock_configure, mock_model_class):
        """Test that Gemini ASR handles API errors properly."""
        # Setup mock to raise an error
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception("API Error")
        mock_model_class.return_value = mock_model

        config = ASRConfig(backend="google", model="gemini-1.5-flash")
        audio = _make_test_wav()

        os.environ["GOOGLE_API_KEY"] = "fake-key-for-test"

        with pytest.raises(ASRError, match="Gemini transcription failed"):
            transcribe(audio, 16000, config)


class TestGeminiTTS:
    """Tests for Gemini TTS backend."""

    def test_gemini_tts_requires_api_key(self):
        """Test that Gemini TTS requires GOOGLE_API_KEY."""
        config = TTSConfig(backend="google", model="gemini-1.5-flash")

        # Remove GOOGLE_API_KEY if it exists
        old_key = os.environ.pop("GOOGLE_API_KEY", None)
        try:
            with pytest.raises(TTSError, match="GOOGLE_API_KEY not configured"):
                synthesize("Hello world", config)
        finally:
            if old_key:
                os.environ["GOOGLE_API_KEY"] = old_key

    def test_gemini_tts_requires_sdk(self):
        """Test that Gemini TTS requires google-generativeai SDK."""
        config = TTSConfig(backend="google", model="gemini-1.5-flash")

        # Set a fake API key
        os.environ["GOOGLE_API_KEY"] = "fake-key-for-test"

        with patch.dict("sys.modules", {"google.generativeai": None}):
            with pytest.raises(TTSError, match="Google Generative AI SDK unavailable"):
                synthesize("Hello world", config)

    @patch("google.generativeai.configure")
    def test_gemini_tts_not_yet_supported(self, mock_configure):
        """Test that Gemini TTS shows proper error for unsupported feature."""
        config = TTSConfig(backend="google", model="gemini-1.5-flash")

        os.environ["GOOGLE_API_KEY"] = "fake-key-for-test"

        # Use proper logger with event method
        logger = voice_logging.get_logger("test")
        with pytest.raises(TTSError, match="Gemini TTS is not yet supported"):
            synthesize("Hello world", config, logger=logger)

    def test_gemini_tts_blocks_realtime_mode(self):
        """Test that Gemini TTS blocks in realtime mode."""
        config = TTSConfig(backend="google", transport="realtime")

        os.environ["GOOGLE_API_KEY"] = "fake-key-for-test"

        # Create a mock logger with event method
        mock_logger = MagicMock()
        
        # Should block before trying to access the backend
        with pytest.raises(TTSError, match="TTS REST disabled when transport=realtime"):
            synthesize("Hello world", config, logger=mock_logger)
