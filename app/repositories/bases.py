import asyncio
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncEngine

from app.repositories._utils import DEFAULT_BASE, invalid_coordinate, normalize_coverage_cities


class BaseRepository(Protocol):
    async def init_schema(self):
        ...

    async def close(self):
        ...

    async def list_bases(self) -> list[dict]:
        ...

    async def create_base(self, data: dict) -> dict:
        ...

    async def update_base(self, base_id: str, data: dict) -> dict | None:
        ...

    async def delete_base(self, base_id: str) -> bool:
        ...


class InMemoryBaseRepository:
    def __init__(self):
        self.bases: dict[str, dict] = {}
        self.lock = asyncio.Lock()

    async def init_schema(self):
        async with self.lock:
            self.bases.setdefault(DEFAULT_BASE["id"], dict(DEFAULT_BASE))

    async def close(self):
        return None

    async def list_bases(self) -> list[dict]:
        async with self.lock:
            return sorted(self.bases.values(), key=lambda b: b["name"])

    async def create_base(self, data: dict) -> dict:
        base = {
            "id": data["id"].strip(),
            "name": data["name"].strip(),
            "city": data["city"].strip(),
            "uf": data.get("uf", "PE").strip().upper(),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "coverage_cities": normalize_coverage_cities(data.get("coverage_cities", [])),
        }
        async with self.lock:
            self.bases[base["id"]] = base
            return dict(base)

    async def update_base(self, base_id: str, data: dict) -> dict | None:
        async with self.lock:
            if base_id not in self.bases:
                return None
            current = self.bases[base_id]
            current["name"] = data["name"].strip()
            current["city"] = data["city"].strip()
            current["uf"] = data.get("uf", current.get("uf", "PE")).strip().upper()
            current["latitude"] = data.get("latitude")
            current["longitude"] = data.get("longitude")
            current["coverage_cities"] = normalize_coverage_cities(data.get("coverage_cities", []))
            return dict(current)

    async def delete_base(self, base_id: str) -> bool:
        if base_id == DEFAULT_BASE["id"]:
            return False
        async with self.lock:
            return self.bases.pop(base_id, None) is not None


class PostgresBaseRepository:
    def __init__(self, engine: AsyncEngine):
        from app.infra.db.tables import create_base_coverage_cities_table, create_bases_table

        self.engine = engine
        self.bases = create_bases_table()
        self.coverage_cities = create_base_coverage_cities_table()

    async def init_schema(self):
        from app.infra.db.tables import metadata

        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.exec_driver_sql("ALTER TABLE bases ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION")
            await connection.exec_driver_sql("ALTER TABLE bases ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION")
            await connection.exec_driver_sql("ALTER TABLE bases ADD COLUMN IF NOT EXISTS uf VARCHAR(2) DEFAULT 'PE'")
            existing = await connection.execute(
                self.bases.select().where(self.bases.c.id == DEFAULT_BASE["id"])
            )
            existing_base = existing.mappings().one_or_none()
            if existing_base is None:
                await connection.execute(
                    self.bases.insert().values(
                        id=DEFAULT_BASE["id"],
                        name=DEFAULT_BASE["name"],
                        city=DEFAULT_BASE["city"],
                        uf=DEFAULT_BASE["uf"],
                        latitude=DEFAULT_BASE["latitude"],
                        longitude=DEFAULT_BASE["longitude"],
                    )
                )
            elif invalid_coordinate(existing_base.get("latitude"), existing_base.get("longitude")):
                await connection.execute(
                    self.bases.update()
                    .where(self.bases.c.id == DEFAULT_BASE["id"])
                    .values(uf=DEFAULT_BASE["uf"], latitude=DEFAULT_BASE["latitude"], longitude=DEFAULT_BASE["longitude"])
                )
            existing_coverage = await self._get_coverage_cities(connection, DEFAULT_BASE["id"])
            if not existing_coverage:
                await self._replace_coverage_cities(connection, DEFAULT_BASE["id"], DEFAULT_BASE["coverage_cities"])

    async def close(self):
        await self.engine.dispose()

    async def list_bases(self) -> list[dict]:
        from sqlalchemy import select

        async with self.engine.connect() as connection:
            result = await connection.execute(select(self.bases).order_by(self.bases.c.name))
            rows = result.mappings().all()
            bases = [dict(row) for row in rows]
            for base in bases:
                base["coverage_cities"] = await self._get_coverage_cities(connection, base["id"])
        return bases

    async def create_base(self, data: dict) -> dict:
        values = {
            "id": data["id"].strip(),
            "name": data["name"].strip(),
            "city": data["city"].strip(),
            "uf": data.get("uf", "PE").strip().upper(),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
        }
        coverage_cities = normalize_coverage_cities(data.get("coverage_cities", []))
        async with self.engine.begin() as connection:
            await connection.execute(self.bases.insert().values(**values))
            await self._replace_coverage_cities(connection, values["id"], coverage_cities)
        return {**values, "coverage_cities": coverage_cities}

    async def update_base(self, base_id: str, data: dict) -> dict | None:
        from sqlalchemy import update

        values = {
            "name": data["name"].strip(),
            "city": data["city"].strip(),
            "uf": data.get("uf", "PE").strip().upper(),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
        }
        coverage_cities = normalize_coverage_cities(data.get("coverage_cities", []))
        async with self.engine.begin() as connection:
            result = await connection.execute(
                update(self.bases).where(self.bases.c.id == base_id).values(**values)
            )
            if result.rowcount > 0:
                await self._replace_coverage_cities(connection, base_id, coverage_cities)
        if result.rowcount == 0:
            return None
        return {"id": base_id, **values, "coverage_cities": coverage_cities}

    async def delete_base(self, base_id: str) -> bool:
        if base_id == DEFAULT_BASE["id"]:
            return False
        async with self.engine.begin() as connection:
            await connection.execute(
                self.coverage_cities.delete().where(self.coverage_cities.c.base_id == base_id)
            )
            result = await connection.execute(
                self.bases.delete().where(self.bases.c.id == base_id)
            )
        return result.rowcount > 0

    async def _get_coverage_cities(self, connection, base_id: str) -> list[str]:
        from sqlalchemy import select

        result = await connection.execute(
            select(self.coverage_cities.c.city)
            .where(self.coverage_cities.c.base_id == base_id)
            .order_by(self.coverage_cities.c.city)
        )
        return [row[0] for row in result.all()]

    async def _replace_coverage_cities(self, connection, base_id: str, cities: list[str]):
        await connection.execute(
            self.coverage_cities.delete().where(self.coverage_cities.c.base_id == base_id)
        )
        for city in normalize_coverage_cities(cities):
            await connection.execute(
                self.coverage_cities.insert().values(base_id=base_id, city=city)
            )
