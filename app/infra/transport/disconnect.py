import asyncio


class DisconnectManager:
    def __init__(self, grace_seconds: float):
        self.grace_seconds = grace_seconds
        self._tasks: dict[tuple[str, str], asyncio.Task] = {}
        self._lock = asyncio.Lock()

    def schedule(self, channel_id: str, usuario: str, coro) -> asyncio.Task:
        key = (channel_id, usuario)
        task = asyncio.create_task(self._run(key, coro))
        self._tasks[key] = task
        return task

    async def cancel(self, channel_id: str, usuario: str) -> bool:
        key = (channel_id, usuario)
        async with self._lock:
            task = self._tasks.pop(key, None)
        if task is None:
            return False
        task.cancel()
        return True

    async def cancel_all(self):
        async with self._lock:
            for task in self._tasks.values():
                task.cancel()

    async def _run(self, key: tuple[str, str], coro):
        try:
            await coro
        finally:
            async with self._lock:
                self._tasks.pop(key, None)
