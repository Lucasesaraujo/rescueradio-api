import asyncio
from typing import Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine

from app.repositories._utils import now_iso, row_to_dict


class OccurrenceRepository(Protocol):
    async def init_schema(self):
        ...

    async def close(self):
        ...

    async def create_occurrence(self, data: dict, created_by: str) -> dict:
        ...

    async def get_occurrence(self, occurrence_id: str) -> dict | None:
        ...

    async def list_occurrences(
        self,
        status: str | None = None,
        base_id: str | None = None,
    ) -> list[dict]:
        ...

    async def update_status(self, occurrence_id: str, status: str) -> None:
        ...


class InMemoryOccurrenceRepository:
    def __init__(self):
        self.occurrences: dict[str, dict] = {}
        self.lock = asyncio.Lock()

    async def init_schema(self):
        return None

    async def close(self):
        return None

    async def create_occurrence(self, data: dict, created_by: str) -> dict:
        occurrence = {
            "id": f"occ-{uuid4().hex[:10]}",
            "base_id": data["base_id"],
            "title": data["title"],
            "type": data["type"],
            "priority": data["priority"],
            "status": "active",
            "address_text": data["address_text"],
            "latitude": data["latitude"],
            "longitude": data["longitude"],
            "description": data.get("description", ""),
            "created_by": created_by,
            "created_at": now_iso(),
        }
        async with self.lock:
            self.occurrences[occurrence["id"]] = occurrence
            return dict(occurrence)

    async def get_occurrence(self, occurrence_id: str) -> dict | None:
        async with self.lock:
            occurrence = self.occurrences.get(occurrence_id)
            return dict(occurrence) if occurrence else None

    async def list_occurrences(
        self,
        status: str | None = None,
        base_id: str | None = None,
    ) -> list[dict]:
        async with self.lock:
            occurrences = list(self.occurrences.values())
        if status:
            occurrences = [o for o in occurrences if o["status"] == status]
        if base_id:
            occurrences = [o for o in occurrences if o["base_id"] == base_id]
        return sorted(occurrences, key=lambda o: o["created_at"], reverse=True)

    async def update_status(self, occurrence_id: str, status: str) -> None:
        async with self.lock:
            occurrence = self.occurrences.get(occurrence_id)
            if occurrence is not None:
                occurrence["status"] = status


class PostgresOccurrenceRepository:
    def __init__(self, engine: AsyncEngine):
        from app.infra.db.tables import create_occurrences_table

        self.engine = engine
        self.occurrences = create_occurrences_table()

    async def init_schema(self):
        from app.infra.db.tables import metadata

        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)

    async def close(self):
        await self.engine.dispose()

    async def create_occurrence(self, data: dict, created_by: str) -> dict:
        occurrence = {
            "id": f"occ-{uuid4().hex[:10]}",
            "base_id": data["base_id"],
            "title": data["title"],
            "type": data["type"],
            "priority": data["priority"],
            "status": "active",
            "address_text": data["address_text"],
            "latitude": data["latitude"],
            "longitude": data["longitude"],
            "description": data.get("description", ""),
            "created_by": created_by,
        }
        async with self.engine.begin() as connection:
            await connection.execute(self.occurrences.insert().values(**occurrence))
        return await self.get_occurrence(occurrence["id"]) or occurrence

    async def get_occurrence(self, occurrence_id: str) -> dict | None:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                self.occurrences.select().where(self.occurrences.c.id == occurrence_id)
            )
            row = result.mappings().one_or_none()
        return row_to_dict(row) if row else None

    async def list_occurrences(
        self,
        status: str | None = None,
        base_id: str | None = None,
    ) -> list[dict]:
        from sqlalchemy import desc, select

        query = select(self.occurrences)
        if status:
            query = query.where(self.occurrences.c.status == status)
        if base_id:
            query = query.where(self.occurrences.c.base_id == base_id)
        query = query.order_by(desc(self.occurrences.c.created_at))

        async with self.engine.connect() as connection:
            result = await connection.execute(query)
            rows = result.mappings().all()
        return [row_to_dict(row) for row in rows]

    async def update_status(self, occurrence_id: str, status: str) -> None:
        from sqlalchemy import update

        async with self.engine.begin() as connection:
            await connection.execute(
                update(self.occurrences)
                .where(self.occurrences.c.id == occurrence_id)
                .values(status=status)
            )
