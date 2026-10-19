"""Python 3.9-compatible ownership and draining of one voice session's tasks."""

from __future__ import annotations

import asyncio


async def cancel_tasks(*tasks):
    """Consume expected child cancellation while propagating caller cancellation."""
    pending = {task for task in tasks if task is not None}
    for task in pending:
        if not task.done():
            task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


class SessionTasks:
    """Keep strong references until completion and reject work during shutdown."""

    def __init__(self, logger):
        self.logger = logger
        self.tasks = set()
        self.closing = False
        self._drain_lock = None

    def create(self, coroutine, *, name):
        """Start owned work and retrieve its outcome even when nobody awaits it."""
        if self.closing:
            coroutine.close()
            raise RuntimeError("voice_session_closing")
        task = asyncio.create_task(coroutine, name=name)
        self.tasks.add(task)
        task.add_done_callback(self._finished)
        return task

    def _finished(self, task):
        """Release completed tasks and report actual failures, not normal cancellation."""
        self.tasks.discard(task)
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                self.logger.event("stream.task.error", task=task.get_name(), error=str(error))

    async def cancel_all(self):
        """Stop admission, cancel and await every owned task exactly once per drain."""
        self.closing = True
        try:
            if self._drain_lock is None:
                self._drain_lock = asyncio.Lock()
            async with self._drain_lock:
                await cancel_tasks(*tuple(self.tasks))
        except asyncio.CancelledError:
            # A caller cancelled while waiting for another drain must still end
            # every child before its outer resource cleanup can close transport.
            await cancel_tasks(*tuple(self.tasks))
            raise
