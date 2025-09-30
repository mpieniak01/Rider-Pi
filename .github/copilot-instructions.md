# Split svc_stream.py – plan
Cel: rozbić `apps/voice/svc_stream.py` na mniejsze moduły (≤600 linii/plik), 1:1 bez regresji.
Podział:
- apps/voice/transport.py — WS connect/reconnect/close/wait_closed (1000/1006), headers, ping/pong.
- apps/voice/state.py — PTT, stany tury, liczniki ciszy i max_turn.
- apps/voice/stream_chunks.py — obróbka audio chunków i payloady session.update.
- apps/voice/service_impl.py — implementacja serwisu; `svc_stream.py` tylko orkiestruje.
Wymagania: nie zmieniaj publicznych nazw; ruff ≤120; `ALSA_SKIP_LSOF=1 pytest -q -k voice` zielone.
