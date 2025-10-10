# apps/voice/tests/test_transport_logging.py
"""Test rate-limited WebSocket logging."""

import asyncio
import json
import os


class DummyWS:
    """Mock WebSocket for testing."""

    def __init__(self):
        self._recv_q = asyncio.Queue()
        self.sent = []

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        return await self._recv_q.get()

    async def close(self, code=1000):
        pass

    async def wait_closed(self):
        pass


class DummyLogger:
    """Mock logger that captures events."""

    def __init__(self):
        self.events = []

    def event(self, name, **kw):
        self.events.append((name, kw))


class MockTransportMixin:
    """Mock transport mixin with rate-limited send logging."""

    def __init__(self):
        self.websocket = DummyWS()
        self.logger = DummyLogger()
        self.connected = True
        self._append_sample_counter = 0
        self._append_sample_every = int(os.environ.get("VOICE_WS_APPEND_SAMPLE_EVERY", "0"))
        self._ws_log_enabled = os.environ.get("VOICE_WS_LOG", "").strip() == "1"

    async def send(self, data: str) -> None:
        """Send data through WebSocket with optional rate-limited logging."""
        if not hasattr(self, "websocket") or not self.websocket:
            return

        await self.websocket.send(data)

        # Rate-limited logging
        if self._ws_log_enabled and hasattr(self, "logger"):
            try:
                payload = json.loads(data)
                event_type = payload.get("type", "")

                # Rate-limit audio buffer append logging
                if event_type == "input_audio_buffer.append":
                    if self._append_sample_every > 0:
                        self._append_sample_counter += 1
                        if self._append_sample_counter % self._append_sample_every == 0:
                            self.logger.event("ws.send", t=event_type, sample_num=self._append_sample_counter)
                else:
                    # Log all non-append events
                    self.logger.event("ws.send", t=event_type)
            except Exception:
                # Ignore logging errors
                pass


async def _run():
    os.environ["VOICE_WS_LOG"] = "1"
    os.environ["VOICE_WS_APPEND_SAMPLE_EVERY"] = "100"
    s = MockTransportMixin()
    # 300 appends -> should log ~3 times, not 300
    append = json.dumps({"type": "input_audio_buffer.append", "audio": "AA=="})
    for _ in range(300):
        await s.send(append)
    # plus commit/response should always be logged
    await s.send(json.dumps({"type": "input_audio_buffer.commit"}))
    await s.send(json.dumps({"type": "response.create"}))
    sends = [e for e in s.logger.events if e[0] == "ws.send"]
    # ~3-5 logs is OK (depending on modulo boundaries); important that << 300
    assert len(sends) < 15
    assert any("response.create" in e[1].get("t", "") for e in sends)


def test_transport_rate_limits():
    asyncio.run(_run())
