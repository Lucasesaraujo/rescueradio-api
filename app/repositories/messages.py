import asyncio
from collections import deque
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncEngine


BRIEFING_SIZE = 50


class MessageRepository(Protocol):
    async def add_message(self, channel_id: str, message: dict):
        ...

    async def clear_channel(self, channel_id: str) -> int:
        ...

    async def get_briefing(self, channel_id: str) -> list[dict]:
        ...

    async def get_channel_messages(self, channel_id: str) -> list[dict]:
        ...


class InMemoryMessageRepository:
    def __init__(self, buffer_size: int = BRIEFING_SIZE):
        self.buffer_size = buffer_size
        self.message_buffer: dict[str, deque[dict]] = {}
        self.lock = asyncio.Lock()

    def _ensure_channel(self, channel_id: str):
        if channel_id not in self.message_buffer:
            self.message_buffer[channel_id] = deque(maxlen=self.buffer_size)

    async def add_message(self, channel_id: str, message: dict):
        async with self.lock:
            self._ensure_channel(channel_id)
            self.message_buffer[channel_id].append(message)

    async def clear_channel(self, channel_id: str) -> int:
        async with self.lock:
            self._ensure_channel(channel_id)
            removed = len(self.message_buffer[channel_id])
            self.message_buffer[channel_id].clear()
            return removed

    async def get_briefing(self, channel_id: str) -> list[dict]:
        async with self.lock:
            self._ensure_channel(channel_id)
            return list(self.message_buffer[channel_id])

    async def get_channel_messages(self, channel_id: str) -> list[dict]:
        return await self.get_briefing(channel_id)


class PostgresMessageRepository:
    def __init__(self, engine: AsyncEngine):
        from app.infra.db.tables import create_channel_messages_table

        self.engine = engine
        self.channel_messages = create_channel_messages_table()

    async def init_schema(self):
        from app.infra.db.tables import metadata

        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)

    async def close(self):
        await self.engine.dispose()

    async def add_message(self, channel_id: str, message: dict):
        async with self.engine.begin() as connection:
            await connection.execute(
                self.channel_messages.insert().values(
                    channel_id=channel_id,
                    type=message["type"],
                    usuario=message["usuario"],
                    timestamp_iso=message["timestamp_iso"],
                    corpo_texto=message["corpo_texto"],
                )
            )

    async def clear_channel(self, channel_id: str) -> int:
        async with self.engine.begin() as connection:
            result = await connection.execute(
                self.channel_messages.delete().where(
                    self.channel_messages.c.channel_id == channel_id
                )
            )
        return int(result.rowcount or 0)

    async def get_briefing(self, channel_id: str) -> list[dict]:
        from sqlalchemy import desc, select

        query = (
            select(
                self.channel_messages.c.type,
                self.channel_messages.c.usuario,
                self.channel_messages.c.timestamp_iso,
                self.channel_messages.c.corpo_texto,
            )
            .where(self.channel_messages.c.channel_id == channel_id)
            .order_by(
                desc(self.channel_messages.c.created_at),
                desc(self.channel_messages.c.id),
            )
            .limit(BRIEFING_SIZE)
        )

        async with self.engine.connect() as connection:
            result = await connection.execute(query)
            rows = result.mappings().all()

        return [
            {
                "type": row["type"],
                "usuario": row["usuario"],
                "timestamp_iso": row["timestamp_iso"],
                "corpo_texto": row["corpo_texto"],
            }
            for row in reversed(rows)
        ]

    async def get_channel_messages(self, channel_id: str) -> list[dict]:
        from sqlalchemy import asc, select

        query = (
            select(
                self.channel_messages.c.type,
                self.channel_messages.c.usuario,
                self.channel_messages.c.timestamp_iso,
                self.channel_messages.c.corpo_texto,
            )
            .where(self.channel_messages.c.channel_id == channel_id)
            .order_by(
                asc(self.channel_messages.c.created_at),
                asc(self.channel_messages.c.id),
            )
        )

        async with self.engine.connect() as connection:
            result = await connection.execute(query)
            rows = result.mappings().all()

        return [
            {
                "type": row["type"],
                "usuario": row["usuario"],
                "timestamp_iso": row["timestamp_iso"],
                "corpo_texto": row["corpo_texto"],
            }
            for row in rows
        ]
