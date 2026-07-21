import asyncio

import pytest

from app.queue.scheduler import RetryTask, TaskScheduler


@pytest.mark.asyncio
async def test_scheduler_runs_many_tasks_in_parallel_and_resizes_safely() -> None:
    active = 0
    peak = 0

    async def worker(_task_id: str) -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.03)
        active -= 1

    scheduler = TaskScheduler(worker, concurrency=6)
    await scheduler.start()
    for index in range(12):
        await scheduler.submit(str(index))
    await asyncio.wait_for(scheduler.queue.join(), timeout=2)
    await asyncio.sleep(0)
    assert peak == 6
    assert scheduler.active_count == 0

    peak = 0
    assert scheduler.set_concurrency(2) == 2
    for index in range(4):
        await scheduler.submit(f"smaller-{index}")
    await asyncio.wait_for(scheduler.queue.join(), timeout=2)
    await asyncio.sleep(0)
    assert peak == 2
    await scheduler.stop()


def test_scheduler_rejects_unsafe_concurrency_values() -> None:
    async def worker(_task_id: str) -> None:
        return None

    scheduler = TaskScheduler(worker)
    with pytest.raises(ValueError, match="1 到 12"):
        scheduler.set_concurrency(13)


@pytest.mark.asyncio
async def test_scheduler_retries_later_without_occupying_a_worker() -> None:
    attempts = 0
    completed = asyncio.Event()

    async def worker(_task_id: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RetryTask(0.04)
        completed.set()

    scheduler = TaskScheduler(worker, concurrency=1)
    await scheduler.start()
    await scheduler.submit("rate-limited")
    for _ in range(20):
        if scheduler.active_count == 0 and scheduler.delayed_count == 1:
            break
        await asyncio.sleep(0.002)
    assert scheduler.active_count == 0
    assert scheduler.delayed_count == 1
    await asyncio.wait_for(completed.wait(), timeout=1)
    assert attempts == 2
    await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_holds_and_releases_a_delayed_task() -> None:
    executed = asyncio.Event()

    async def worker(_task_id: str) -> None:
        executed.set()

    scheduler = TaskScheduler(worker, concurrency=1)
    await scheduler.start()
    await scheduler.submit("paused", delay_seconds=0.08)
    await asyncio.sleep(0.01)
    scheduler.hold(["paused"])
    await asyncio.sleep(0.09)
    assert not executed.is_set()
    assert scheduler.held_count == 1
    scheduler.release(["paused"])
    await asyncio.wait_for(executed.wait(), timeout=1)
    await scheduler.stop()


@pytest.mark.asyncio
async def test_released_active_task_can_requeue_after_pause_race() -> None:
    first_attempt_claimed = asyncio.Event()
    allow_retry = asyncio.Event()
    completed = asyncio.Event()
    attempts = 0

    async def worker(_task_id: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            first_attempt_claimed.set()
            await allow_retry.wait()
            raise RetryTask(0)
        completed.set()

    scheduler = TaskScheduler(worker, concurrency=1)
    await scheduler.start()
    await scheduler.submit("pause-race")
    await asyncio.wait_for(first_attempt_claimed.wait(), timeout=1)

    scheduler.hold(["pause-race"])
    scheduler.release(["pause-race"])
    allow_retry.set()

    await asyncio.wait_for(completed.wait(), timeout=1)
    assert attempts == 2
    await scheduler.stop()
