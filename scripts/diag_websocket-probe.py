#!/usr/bin/env python3
import asyncio
import json
import os

import websockets

URL = os.environ.get(
    "OPENAI_REALTIME_ENDPOINT", "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17"
)
HDRS = {
    "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}",
    "OpenAI-Beta": "realtime=v1",
}


async def main():
    async with websockets.connect(URL, extra_headers=HDRS, max_size=None, compression=None) as ws:
        await ws.send(json.dumps({"type": "session.update", "session": {"modalities": ["text", "audio"]}}))
        await ws.send(json.dumps({"type": "response.create", "response": {"instructions": "Say 'pong' and stop."}}))
        for _ in range(20):
            msg = await ws.recv()
            print(msg)


if __name__ == "__main__":
    asyncio.run(main())
