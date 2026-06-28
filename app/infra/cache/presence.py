import asyncio
from typing import Protocol


class PresenceService(Protocol):
    async def connect(self, channel_id: str, usuario: str):
        ...

    async def disconnect(self, channel_id: str, usuario: str):
        ...

    async def get_active_members(self, channel_id: str) -> list[dict]:
        ...

    async def close(self):
        ...

    async def clear_all(self):
        ...


class InMemoryPresenceService:
    def __init__(self):
        self.members_by_channel: dict[str, dict[str, str]] = {}
        self.lock = asyncio.Lock()

    async def connect(self, channel_id: str, usuario: str):
        async with self.lock:
            self.members_by_channel.setdefault(channel_id, {})[usuario] = "online"

    async def disconnect(self, channel_id: str, usuario: str):
        async with self.lock:
            channel_members = self.members_by_channel.setdefault(channel_id, {})
            channel_members.pop(usuario, None)

    async def get_active_members(self, channel_id: str) -> list[dict]:
        async with self.lock:
            channel_members = self.members_by_channel.setdefault(channel_id, {})
            return [
                {"usuario": usuario, "status": status}
                for usuario, status in channel_members.items()
            ]

    async def close(self):
        return None

    async def clear_all(self):
        async with self.lock:
            self.members_by_channel.clear()


class RedisPresenceService:
    def __init__(self, redis_url: str):
        from redis.asyncio import Redis

        self.redis = Redis.from_url(redis_url, decode_responses=True)

    async def connect(self, channel_id: str, usuario: str):
        await self.redis.sadd(self._channel_key(channel_id), usuario)

    async def disconnect(self, channel_id: str, usuario: str):
        await self.redis.srem(self._channel_key(channel_id), usuario)

    async def get_active_members(self, channel_id: str) -> list[dict]:
        members = await self.redis.smembers(self._channel_key(channel_id))
        return [
            {"usuario": usuario, "status": "online"}
            for usuario in sorted(members)
        ]

    async def ping(self):
        await self.redis.ping()

    async def close(self):
        await self.redis.aclose()

    async def clear_all(self):
        async for key in self.redis.scan_iter(match="presence:*"):
            await self.redis.delete(key)

    def _channel_key(self, channel_id: str) -> str:
        return f"presence:{channel_id}"
