# apps/voice/tests/test_transport_logging.py
import asyncio
import json
import os

from apps.voice.transport import StreamingVoiceTransportMixin


class DummyWS:
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
    def __init__(self):
        self.events = []

    def event(self, name, **kw):
        self.events.append((name, kw))


class Svc(StreamingVoiceTransportMixin):
    def __init__(self):
        self.websocket = DummyWS()
        self.logger = DummyLogger()
        self.connected = True
        self.stream_cfg = type("Cfg", (), {"ping_interval_s": 10})()

    def _get_auth_header(self):
        return "test"

    async def _send_session_update(self):
        pass

    def _publish_error(self, *a, **k):
        pass


async def _run():
    os.environ["VOICE_WS_LOG"] = "1"
    os.environ["VOICE_WS_APPEND_SAMPLE_EVERY"] = "100"
    s = Svc()
    # 300 appendów -> powinno zalogować ~3 razy, nie 300
    append = json.dumps({"type": "input_audio_buffer.append", "audio": "AA=="})
    for _ in range(300):
        await s.send(append)
    # plus commit/response powinny wejść zawsze
    await s.send(json.dumps({"type": "input_audio_buffer.commit"}))
    await s.send(json.dumps({"type": "response.create"}))
    sends = [e for e in s.logger.events if e[0] == "ws.send"]
    # ~3-5 logów jest OK (zależnie od granic modulo); ważne że << 300
    assert len(sends) < 15
    assert any("response.create" in e[1].get("t", "") for e in sends)


def test_transport_rate_limits():
    asyncio.run(_run())
