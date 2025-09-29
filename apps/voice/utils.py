# apps/voice/utils.py
from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any


def run_sync(coro_or_value: Any, *, timeout: float | None = None) -> Any:
    """
    Uruchamia coroutine/awaitable z kodu synchronicznego bezpiecznie i przewidywalnie.

    Zasady:
    - Jeśli `coro_or_value` NIE jest coroutine/awaitable → zwróć wartość bez zmian.
    - Jeśli wywołano z WNĘTRZA działającej pętli asyncio (ten sam wątek):
        * nie wolno blokować bieżącej pętli; zwracamy istniejący Future/Task,
          a jeśli to „goła” coroutine – tworzymy Task przez `asyncio.create_task(...)`.
        * `timeout` w tym trybie nie jest tu egzekwowany — caller może użyć `asyncio.wait_for(...)`.
    - Jeśli wywołano SPOZA pętli asyncio:
        * uruchamiamy coroutine do końca przez `asyncio.run(...)`;
        * jeśli podano `timeout`, owijamy w `asyncio.wait_for(...)`.

    :param coro_or_value: coroutine, awaitable lub zwykła wartość
    :param timeout: opcjonalny timeout (sekundy) — tylko dla ścieżki z asyncio.run
    :return: wynik coroutine (spoza pętli) albo Task/Future (wewnątrz pętli),
             lub wejściowa wartość jeśli parametr nie-async.
    """
    # Szybka ścieżka: zwykła wartość
    is_coro = asyncio.iscoroutine(coro_or_value)
    is_awaitable = isinstance(coro_or_value, Awaitable)
    if not is_coro and not is_awaitable:
        return coro_or_value

    # Próba pobrania bieżącej pętli — powiedzie się tylko w wątku pętli
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    # W aktywnej pętli: nie blokujemy
    if loop and loop.is_running():
        # Jeśli to już Future/Task — oddaj jak jest
        if isinstance(coro_or_value, (asyncio.Future, asyncio.Task)):
            return coro_or_value
        # Jeśli to "goła" coroutine — opakuj jako Task
        return asyncio.create_task(coro_or_value)  # type: ignore[arg-type]

    # Poza pętlą (lub w innym wątku bez pętli): uruchom do końca
    async def _runner():
        if timeout is not None:
            return await asyncio.wait_for(coro_or_value, timeout=timeout)  # type: ignore[arg-type]
        return await coro_or_value  # type: ignore[arg-type]

    return asyncio.run(_runner())
