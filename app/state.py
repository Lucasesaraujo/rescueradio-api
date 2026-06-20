from collections import deque
from typing import Protocol


BRIEFING_SIZE = 50


class MessageRepository(Protocol):
    async def add_message(self, channel_id: str, message: dict):
        ...

    async def get_briefing(self, channel_id: str) -> list[dict]:
        ...


class InMemoryMessageRepository:
    def __init__(self, buffer_size: int = BRIEFING_SIZE):
        self.buffer_size = buffer_size
        self.message_buffer: dict[str, deque[dict]] = {}

    def ensure_channel(self, channel_id: str):
        if channel_id not in self.message_buffer:
            self.message_buffer[channel_id] = deque(maxlen=self.buffer_size)

    async def add_message(self, channel_id: str, message: dict):
        self.ensure_channel(channel_id)
        self.message_buffer[channel_id].append(message)

    async def get_briefing(self, channel_id: str) -> list[dict]:
        self.ensure_channel(channel_id)
        return list(self.message_buffer[channel_id])


class PostgresMessageRepository:
    def __init__(self, database_url: str):
        from app.database import create_channel_messages_table
        from sqlalchemy.ext.asyncio import create_async_engine

        self.engine = create_async_engine(database_url)
        self.channel_messages = create_channel_messages_table()

    async def init_schema(self):
        from app.database import metadata

        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)

    async def close(self):
        await self.engine.dispose()

    async def add_message(self, channel_id: str, message: dict):
        insert_statement = self.channel_messages.insert().values(
            channel_id=channel_id,
            type=message["type"],
            usuario=message["usuario"],
            timestamp_iso=message["timestamp_iso"],
            corpo_texto=message["corpo_texto"],
        )

        async with self.engine.begin() as connection:
            await connection.execute(insert_statement)

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
