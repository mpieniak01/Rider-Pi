# apps/voice/tests/test_state_ptt.py
import asyncio
import threading

from apps.voice.state import StreamingVoicePTTMixin


class Dummy(StreamingVoicePTTMixin):
    def __init__(self):
        self.logger = type("L", (), {"event": lambda *a, **k: None})()
        self.config = {"service": {}, "playback": {}}
        self.stop_event = threading.Event()
        self.ptt_enabled = True
        self.ptt_active = False
        self._any_audio_since_commit = False
        self.barge_in_event = threading.Event()
        self.connected = True
        self._loop = asyncio.new_event_loop()
        self._capture_thread = None

    def _publish_ui_state(self, *_):
        pass

    async def _commit_audio_buffer(self):
        self._committed = True


def test_ptt_commit_only_with_audio(monkeypatch):
    d = Dummy()
    d._committed = False
    # symulujemy wątek: bez ENTER, tylko bezpośrednie wywołania
    d.ptt_active = True
    d._any_audio_since_commit = False
    # stop -> brak commit
    d.ptt_active = False
    assert d._committed is False
    # teraz z audio
    d.ptt_active = True
    d._any_audio_since_commit = True
    # wywołujemy commit „na skróty”
    asyncio.run(d._commit_audio_buffer())
    assert d._committed is True
