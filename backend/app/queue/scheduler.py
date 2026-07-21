import asyncio
from collections.abc import Awaitable, Callable, Iterable


class RetryTask(Exception):
    """Ask the scheduler to run the same persisted task again later."""

    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = max(0.0, float(delay_seconds))
        super().__init__(f"retry in {self.delay_seconds:.3f}s")


class TaskScheduler:
    MIN_CONCURRENCY = 1
    MAX_CONCURRENCY = 12

    def __init__(self, worker: Callable[[str], Awaitable[None]], concurrency: int = 8) -> None:
        self.worker = worker
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.concurrency = self._validated_concurrency(concurrency)
        self._dispatcher: asyncio.Task[None] | None = None
        self._active: dict[asyncio.Task[None], str] = {}
        self._queued_ids: set[str] = set()
        self._delayed: dict[str, asyncio.Task[None]] = {}
        self._delay_deadlines: dict[str, float] = {}
        self._held_ids: set[str] = set()
        self._held_waiting: dict[str, float | None] = {}
        self._capacity_changed = asyncio.Event()

    @classmethod
    def _validated_concurrency(cls, value: int) -> int:
        if not cls.MIN_CONCURRENCY <= value <= cls.MAX_CONCURRENCY:
            raise ValueError(
                f"并发任务数必须在 {cls.MIN_CONCURRENCY} 到 {cls.MAX_CONCURRENCY} 之间"
            )
        return value

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def queued_count(self) -> int:
        return len(self._queued_ids) + len(self._delayed) + len(self._held_waiting)

    @property
    def delayed_count(self) -> int:
        return len(self._delayed)

    @property
    def held_count(self) -> int:
        return len(self._held_ids)

    async def start(self) -> None:
        if self._dispatcher is None:
            self._capacity_changed.set()
            self._dispatcher = asyncio.create_task(self._dispatch())

    def set_concurrency(self, value: int) -> int:
        self.concurrency = self._validated_concurrency(value)
        self._capacity_changed.set()
        return self.concurrency

    def _is_known(self, task_id: str) -> bool:
        return (
            task_id in self._queued_ids
            or task_id in self._delayed
            or task_id in self._held_waiting
            or task_id in self._active.values()
        )

    async def submit(self, task_id: str, delay_seconds: float = 0) -> bool:
        if self._is_known(task_id):
            return False
        if task_id in self._held_ids:
            deadline = (
                asyncio.get_running_loop().time() + delay_seconds
                if delay_seconds > 0
                else None
            )
            self._held_waiting[task_id] = deadline
        elif delay_seconds > 0:
            self._schedule_delayed(task_id, delay_seconds)
        else:
            self._enqueue_now(task_id)
        return True

    def hold(self, task_ids: Iterable[str]) -> None:
        for task_id in task_ids:
            self._held_ids.add(task_id)
            delayed = self._delayed.pop(task_id, None)
            deadline = self._delay_deadlines.pop(task_id, None)
            if delayed is not None:
                delayed.cancel()
                self._held_waiting[task_id] = deadline

    def release(self, task_ids: Iterable[str]) -> None:
        loop = asyncio.get_running_loop()
        for task_id in task_ids:
            self._held_ids.discard(task_id)
            if task_id not in self._held_waiting:
                continue
            deadline = self._held_waiting.pop(task_id)
            remaining = max(0.0, deadline - loop.time()) if deadline is not None else 0.0
            if remaining > 0:
                self._schedule_delayed(task_id, remaining)
            elif task_id not in self._queued_ids and task_id not in self._active.values():
                self._enqueue_now(task_id)

    def _enqueue_now(self, task_id: str) -> None:
        self._queued_ids.add(task_id)
        self.queue.put_nowait(task_id)

    def _schedule_delayed(self, task_id: str, delay_seconds: float) -> None:
        deadline = asyncio.get_running_loop().time() + max(0.0, delay_seconds)
        if task_id in self._held_ids:
            self._held_waiting[task_id] = deadline
            return
        self._delay_deadlines[task_id] = deadline
        delayed = asyncio.create_task(self._delay_then_enqueue(task_id, deadline))
        self._delayed[task_id] = delayed

    async def _delay_then_enqueue(self, task_id: str, deadline: float) -> None:
        current = asyncio.current_task()
        try:
            await asyncio.sleep(max(0.0, deadline - asyncio.get_running_loop().time()))
        except asyncio.CancelledError:
            return
        if self._delayed.get(task_id) is not current:
            return
        self._delayed.pop(task_id, None)
        self._delay_deadlines.pop(task_id, None)
        if task_id in self._held_ids:
            self._held_waiting[task_id] = deadline
        else:
            self._enqueue_now(task_id)

    async def _wait_for_capacity(self) -> None:
        while self.active_count >= self.concurrency:
            self._capacity_changed.clear()
            if self.active_count < self.concurrency:
                return
            await self._capacity_changed.wait()

    def _task_finished(self, task: asyncio.Task[None]) -> None:
        self._active.pop(task, None)
        self._capacity_changed.set()
        if task.cancelled():
            return
        task.exception()

    async def _execute(self, task_id: str) -> None:
        try:
            await self.worker(task_id)
        except RetryTask as retry:
            self._schedule_delayed(task_id, retry.delay_seconds)
        finally:
            self.queue.task_done()

    async def _dispatch(self) -> None:
        while True:
            await self._wait_for_capacity()
            task_id = await self.queue.get()
            self._queued_ids.discard(task_id)
            if task_id in self._held_ids:
                self._held_waiting.setdefault(task_id, None)
                self.queue.task_done()
                continue
            task = asyncio.create_task(self._execute(task_id))
            self._active[task] = task_id
            task.add_done_callback(self._task_finished)

    async def stop(self) -> None:
        dispatcher = self._dispatcher
        self._dispatcher = None
        if dispatcher is not None:
            dispatcher.cancel()
            await asyncio.gather(dispatcher, return_exceptions=True)
        delayed = tuple(self._delayed.values())
        for task in delayed:
            task.cancel()
        if delayed:
            await asyncio.gather(*delayed, return_exceptions=True)
        active = tuple(self._active)
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
        self._active.clear()
        self._queued_ids.clear()
        self._delayed.clear()
        self._delay_deadlines.clear()
        self._held_ids.clear()
        self._held_waiting.clear()
