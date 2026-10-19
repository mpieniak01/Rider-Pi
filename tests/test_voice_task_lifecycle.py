"""Task ownership and cancellation regressions without network or audio devices."""

from __future__ import annotations

import asyncio
import gc
import inspect
import weakref
from unittest.mock import Mock

import pytest

from apps.voice.stream.task_lifecycle import SessionTasks, cancel_tasks


@pytest.mark.asyncio
async def test_owned_task_survives_until_drained_and_cancellation_is_expected():
    """An otherwise unreferenced task remains owned until its terminal outcome."""
    owner = SessionTasks(Mock())
    started = asyncio.Event()

    async def waiting():
        started.set()
        await asyncio.Future()

    task = owner.create(waiting(), name="transcript")
    reference = weakref.ref(task)
    await started.wait()
    del task
    gc.collect()
    assert reference() in owner.tasks
    await owner.cancel_all()
    assert owner.tasks == set()
    owner.logger.event.assert_not_called()


@pytest.mark.asyncio
async def test_completed_task_failure_is_retrieved_and_reported_once():
    """Background failures are retrieved rather than becoming lost-task warnings."""
    logger = Mock()
    owner = SessionTasks(logger)

    async def fail():
        raise RuntimeError("transcript failed")

    task = owner.create(fail(), name="transcript")
    await asyncio.wait({task})
    await asyncio.sleep(0)
    assert owner.tasks == set()
    logger.event.assert_called_once_with("stream.task.error", task="transcript", error="transcript failed")


@pytest.mark.asyncio
async def test_successful_task_is_released_without_error():
    """Normal completion releases the strong reference without a failure event."""
    owner = SessionTasks(Mock())
    task = owner.create(asyncio.sleep(0), name="complete")
    await task
    await asyncio.sleep(0)
    assert owner.tasks == set()
    owner.logger.event.assert_not_called()


@pytest.mark.asyncio
async def test_shutdown_rejects_new_work_and_closes_rejected_coroutine():
    """Late transcripts cannot create detached work while the session is closing."""
    owner = SessionTasks(Mock())
    await owner.cancel_all()
    coroutine = asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="voice_session_closing"):
        owner.create(coroutine, name="late")
    assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED
    assert owner.tasks == set()


@pytest.mark.asyncio
async def test_cancelled_child_does_not_cancel_its_draining_parent():
    """Expected child cancellation is consumed; all siblings still terminate."""
    first = asyncio.create_task(asyncio.sleep(60))
    second = asyncio.create_task(asyncio.sleep(60))
    first.cancel()
    await cancel_tasks(first, second, None)
    assert first.cancelled()
    assert second.cancelled()


@pytest.mark.asyncio
async def test_parent_cancellation_is_propagated_while_draining_children():
    """Cancelling the joiner is distinct from a child reporting cancellation."""
    started = asyncio.Event()
    cleaning = asyncio.Event()
    release = asyncio.Event()

    async def child():
        started.set()
        try:
            await asyncio.Future()
        finally:
            cleaning.set()
            await release.wait()

    worker = asyncio.create_task(child())
    await started.wait()
    parent = asyncio.create_task(cancel_tasks(worker))
    await cleaning.wait()
    parent.cancel()
    with pytest.raises(asyncio.CancelledError):
        await parent
    assert worker.done()


@pytest.mark.asyncio
async def test_concurrent_drains_do_not_cancel_child_cleanup_twice():
    """Only one drain requests cancellation; another waits for the same boundary."""
    owner = SessionTasks(Mock())
    started = asyncio.Event()
    cleaning = asyncio.Event()
    release = asyncio.Event()
    finished = []

    async def child():
        started.set()
        try:
            await asyncio.Future()
        finally:
            cleaning.set()
            await release.wait()
            finished.append(True)

    owner.create(child(), name="child")
    await started.wait()
    first = asyncio.create_task(owner.cancel_all())
    await cleaning.wait()
    second = asyncio.create_task(owner.cancel_all())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)
    assert finished == [True]
    assert owner.tasks == set()


@pytest.mark.asyncio
async def test_cancelled_waiter_drains_children_before_leaving_shutdown_boundary():
    """Cancellation while waiting for another drain cannot leave live child work."""
    owner = SessionTasks(Mock())
    started = asyncio.Event()
    cleaning = asyncio.Event()

    async def child():
        started.set()
        try:
            await asyncio.Future()
        finally:
            cleaning.set()
            await asyncio.Future()

    owner.create(child(), name="child")
    await started.wait()
    first = asyncio.create_task(owner.cancel_all())
    await cleaning.wait()
    second = asyncio.create_task(owner.cancel_all())
    await asyncio.sleep(0)
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    assert owner.tasks == set()
    await first
