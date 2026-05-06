import asyncio
from unittest.mock import patch

import pytest

import core.task_tracker as tt


@pytest.fixture(autouse=True)
def clear_tasks():
    tt._inflight_tasks.clear()
    yield
    tt._inflight_tasks.clear()


@pytest.mark.asyncio
async def test_track_task():
    task = asyncio.create_task(asyncio.sleep(0))
    tt.track_task(task)
    assert task in tt._inflight_tasks


@pytest.mark.asyncio
async def test_wait_for_inflight_no_tasks():
    await tt.wait_for_inflight()


@pytest.mark.asyncio
async def test_wait_for_inflight_completes_tasks():
    completed = False

    async def quick_task():
        nonlocal completed
        completed = True

    task = asyncio.create_task(quick_task())
    tt.track_task(task)

    await tt.wait_for_inflight()

    assert completed
    assert len(tt._inflight_tasks) == 0


@pytest.mark.asyncio
async def test_wait_for_inflight_cancels_slow_tasks():
    cancelled = False

    async def slow_task():
        nonlocal cancelled
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            cancelled = True

    with patch.object(tt, "SHUTDOWN_TIMEOUT", 0.1):
        task = asyncio.create_task(slow_task())
        tt.track_task(task)
        await tt.wait_for_inflight()

    assert cancelled


@pytest.mark.asyncio
async def test_task_removed_after_await():
    async def quick():
        pass

    task = asyncio.create_task(quick())
    tt.track_task(task)
    await task
    await asyncio.sleep(0)

    assert task not in tt._inflight_tasks
