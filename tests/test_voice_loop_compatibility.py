"""Python 3.9 lock affinity: construct sync, then contend inside asyncio.run."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from apps.voice.stream.svc_streaming import StreamingVoiceService
from apps.voice.stream.task_lifecycle import SessionTasks
from apps.voice.stream.transport import WebSocketTransport


@pytest.mark.parametrize("kind", ["registry", "service", "transport"])
def test_sync_construction_does_not_bind_shutdown_to_the_wrong_loop(kind):
    """Contended shutdown must use the running loop, not the construction loop."""
    construction_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(construction_loop)
    try:
        if kind == "registry":
            target = SessionTasks(Mock())
        elif kind == "service":
            target = StreamingVoiceService({})
            target.transport = AsyncMock()
            target._cleanup_workers = Mock()
            target.ptt_state = Mock()
            target._publish_ui_state = Mock()
        else:
            target = WebSocketTransport("ws://localhost.invalid/voice", "", logger=Mock())
            target.websocket = AsyncMock()
            target._use_async = True

        async def exercise():
            entered = asyncio.Event()
            release = asyncio.Event()

            async def block():
                entered.set()
                await release.wait()

            if kind == "registry":
                child_started = asyncio.Event()

                async def child():
                    child_started.set()
                    try:
                        await asyncio.Future()
                    finally:
                        await block()

                target.create(child(), name="pending")
                await child_started.wait()
                close = target.cancel_all
            else:
                if kind == "service":
                    socket = target.transport
                    socket.close.side_effect = block
                else:
                    socket = target.websocket

                    async def close_socket(**_kwargs):
                        await block()

                    socket.close.side_effect = close_socket
                close = target.close
            first = asyncio.create_task(close())
            await entered.wait()
            second = asyncio.create_task(close())
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(first, second)
            if kind == "registry":
                assert not target.tasks
            else:
                socket.close.assert_awaited_once()

        asyncio.run(exercise())
    finally:
        construction_loop.close()
        asyncio.set_event_loop(None)
