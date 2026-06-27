import asyncio
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4


DEFAULT_BASE = {
    "id": "base-central",
    "name": "Base Central",
    "city": "Recife",
    "latitude": -8.0476,
    "longitude": -34.877,
    "coverage_cities": ["Recife", "Olinda", "Paulista", "Jaboatao dos Guararapes", "Camaragibe"],
}

DEFAULT_FUNCTIONS = [
    {"id": "socorrista", "label": "Socorrista"},
    {"id": "condutor", "label": "Condutor"},
    {"id": "enfermeiro", "label": "Enfermeiro"},
    {"id": "medico", "label": "Medico"},
    {"id": "comandante_operacional", "label": "Comandante operacional"},
    {"id": "operador_radio", "label": "Operador de radio"},
    {"id": "resgate_tecnico", "label": "Resgate tecnico"},
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def serialize_skills(skills: list[str]) -> str:
    return ",".join(skill.strip() for skill in skills if skill.strip())


def parse_skills(skills: str) -> list[str]:
    return [skill for skill in skills.split(",") if skill]


def normalize_coverage_cities(cities: list[str]) -> list[str]:
    seen = set()
    normalized = []
    for city in cities:
        value = str(city).strip()
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        normalized.append(value)
    return normalized


def invalid_coordinate(latitude: float | None, longitude: float | None) -> bool:
    if latitude is None or longitude is None:
        return True
    if abs(float(latitude)) < 0.0001 and abs(float(longitude)) < 0.0001:
        return True
    return not (-90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180)


def derive_display_name(full_name: str) -> str:
    parts = [part for part in full_name.strip().split() if part]
    if len(parts) <= 1:
        return full_name.strip()
    return f"{parts[0]} {parts[-1]}"


def derive_callsign_base(full_name: str) -> str:
    initials = "".join(part[0].lower() for part in full_name.strip().split() if part)
    return initials or "op"


class DomainRepository(Protocol):
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

    async def list_functions(self) -> list[dict]:
        ...

    async def create_function(self, data: dict) -> dict:
        ...

    async def update_function(self, function_id: str, data: dict) -> dict | None:
        ...

    async def delete_function(self, function_id: str) -> bool:
        ...

    async def get_profile(self, username: str) -> dict | None:
        ...

    async def upsert_profile(self, username: str, data: dict) -> dict:
        ...

    async def update_presence(
        self,
        username: str,
        connection_status: str,
        last_seen_at: str | None = None,
    ) -> dict | None:
        ...

    async def list_operator_profiles(
        self,
        base_id: str | None = None,
        status: str | None = None,
        skill: str | None = None,
    ) -> list[dict]:
        ...

    async def create_occurrence(self, data: dict, created_by: str) -> dict:
        ...

    async def list_occurrences(
        self,
        status: str | None = None,
        base_id: str | None = None,
    ) -> list[dict]:
        ...

    async def create_operation(
        self,
        occurrence: dict,
        member_users: list[dict],
        created_by: str,
    ) -> dict:
        ...

    async def add_operation_members(
        self,
        operation_id: str,
        member_users: list[dict],
        assigned_by: str,
    ) -> list[dict] | None:
        ...

    async def close_operation(
        self,
        operation_id: str,
        summary: str,
        outcome: str,
        closed_by: str,
    ) -> dict | None:
        ...

    async def list_operations(
        self,
        status: str | None = None,
        base_id: str | None = None,
    ) -> list[dict]:
        ...

    async def get_operation(self, operation_id: str) -> dict | None:
        ...

    async def get_operation_by_channel(self, channel_id: str) -> dict | None:
        ...

    async def get_operation_audit(self, operation_id: str, messages: list[dict]) -> dict | None:
        ...


class InMemoryDomainRepository:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.bases: dict[str, dict] = {}
        self.functions: dict[str, dict] = {}
        self.profiles: dict[str, dict] = {}
        self.occurrences: dict[str, dict] = {}
        self.operations: dict[str, dict] = {}
        self.members: dict[str, dict[str, dict]] = {}
        self.status_events: dict[str, list[dict]] = {}

    async def init_schema(self):
        async with self.lock:
            self.bases.setdefault(DEFAULT_BASE["id"], dict(DEFAULT_BASE))
            for function in DEFAULT_FUNCTIONS:
                self.functions.setdefault(function["id"], dict(function))

    async def close(self):
        return None

    async def list_bases(self) -> list[dict]:
        async with self.lock:
            return sorted(self.bases.values(), key=lambda item: item["name"])

    async def create_base(self, data: dict) -> dict:
        base = {
            "id": data["id"].strip(),
            "name": data["name"].strip(),
            "city": data["city"].strip(),
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
            current["latitude"] = data.get("latitude")
            current["longitude"] = data.get("longitude")
            current["coverage_cities"] = normalize_coverage_cities(data.get("coverage_cities", []))
            return dict(current)

    async def delete_base(self, base_id: str) -> bool:
        if base_id == DEFAULT_BASE["id"]:
            return False
        async with self.lock:
            return self.bases.pop(base_id, None) is not None

    async def list_functions(self) -> list[dict]:
        async with self.lock:
            return sorted(self.functions.values(), key=lambda item: item["label"])

    async def create_function(self, data: dict) -> dict:
        function = {"id": data["id"].strip(), "label": data["label"].strip()}
        async with self.lock:
            self.functions[function["id"]] = function
            return dict(function)

    async def update_function(self, function_id: str, data: dict) -> dict | None:
        async with self.lock:
            if function_id not in self.functions:
                return None
            self.functions[function_id]["label"] = data["label"].strip()
            return dict(self.functions[function_id])

    async def delete_function(self, function_id: str) -> bool:
        async with self.lock:
            return self.functions.pop(function_id, None) is not None

    async def get_profile(self, username: str) -> dict | None:
        async with self.lock:
            profile = self.profiles.get(username)
            return self._profile_dict(profile) if profile else None

    async def upsert_profile(self, username: str, data: dict) -> dict:
        full_name = (data.get("full_name") or data["operational_name"]).strip()
        callsign = (data.get("callsign") or derive_callsign_base(full_name)).strip().lower()
        profile = {
            "username": username,
            "full_name": full_name,
            "callsign": callsign,
            "operational_name": data["operational_name"].strip(),
            "base_id": data["base_id"].strip(),
            "function": data["function"].strip(),
            "contact": data["contact"].strip(),
            "status": data["status"].strip(),
            "connection_status": data.get("connection_status", "offline"),
            "last_seen_at": data.get("last_seen_at"),
            "skills": list(data.get("skills", [])),
            "updated_at": now_iso(),
        }
        async with self.lock:
            taken = {
                item.get("callsign")
                for key, item in self.profiles.items()
                if key != username and item.get("callsign")
            }
            if callsign in taken:
                suffix = 2
                while f"{callsign}{suffix}" in taken:
                    suffix += 1
                profile["callsign"] = f"{callsign}{suffix}"
            self.profiles[username] = profile
            return self._profile_dict(profile)

    async def update_presence(
        self,
        username: str,
        connection_status: str,
        last_seen_at: str | None = None,
    ) -> dict | None:
        async with self.lock:
            profile = self.profiles.get(username)
            if profile is None:
                return None
            profile["connection_status"] = connection_status
            if last_seen_at is not None:
                profile["last_seen_at"] = last_seen_at
            profile["updated_at"] = now_iso()
            return self._profile_dict(profile)

    async def list_operator_profiles(
        self,
        base_id: str | None = None,
        status: str | None = None,
        skill: str | None = None,
    ) -> list[dict]:
        async with self.lock:
            profiles = list(self.profiles.values())

        if base_id:
            profiles = [profile for profile in profiles if profile["base_id"] == base_id]
        if status:
            profiles = [profile for profile in profiles if profile["status"] == status]
        if skill:
            profiles = [
                profile
                for profile in profiles
                if skill.lower() in [item.lower() for item in profile["skills"]]
            ]

        return sorted(
            [self._profile_dict(profile) for profile in profiles],
            key=lambda item: item["operational_name"],
        )

    def _profile_dict(self, profile: dict) -> dict:
        data = dict(profile)
        data["full_name"] = data.get("full_name") or data.get("operational_name", "")
        data["display_name"] = derive_display_name(data["full_name"])
        data["callsign"] = data.get("callsign") or derive_callsign_base(data["full_name"])
        data["connection_status"] = data.get("connection_status") or "offline"
        return data

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

    async def list_occurrences(
        self,
        status: str | None = None,
        base_id: str | None = None,
    ) -> list[dict]:
        async with self.lock:
            occurrences = list(self.occurrences.values())

        if status:
            occurrences = [occurrence for occurrence in occurrences if occurrence["status"] == status]
        if base_id:
            occurrences = [occurrence for occurrence in occurrences if occurrence["base_id"] == base_id]

        return sorted(occurrences, key=lambda item: item["created_at"], reverse=True)

    async def create_operation(
        self,
        occurrence: dict,
        member_users: list[dict],
        created_by: str,
    ) -> dict:
        operation_id = f"op-{uuid4().hex[:10]}"
        operation = {
            "id": operation_id,
            "occurrence_id": occurrence["id"],
            "base_id": occurrence["base_id"],
            "channel_id": f"operacao:{operation_id}",
            "status": "active",
            "created_by": created_by,
            "created_at": now_iso(),
            "closed_by": None,
            "closed_at": None,
            "closing_summary": None,
            "outcome": None,
            "occurrence": occurrence,
            "members": [],
        }
        async with self.lock:
            self.operations[operation_id] = operation
            self.members[operation_id] = {}
            self.status_events[operation_id] = [
                {
                    "operation_id": operation_id,
                    "status": "active",
                    "username": created_by,
                    "note": "Operacao criada.",
                    "created_at": now_iso(),
                }
            ]
        await self.add_operation_members(operation_id, member_users, created_by)
        return await self.get_operation(operation_id) or operation

    async def add_operation_members(
        self,
        operation_id: str,
        member_users: list[dict],
        assigned_by: str,
    ) -> list[dict] | None:
        async with self.lock:
            operation = self.operations.get(operation_id)
            if operation is None:
                return None
            if operation["status"] == "closed":
                return list(self.members.get(operation_id, {}).values())

            operation_members = self.members.setdefault(operation_id, {})
            for user in member_users:
                operation_members[user["username"]] = {
                    "operation_id": operation_id,
                    "username": user["username"],
                    "display_name": user["display_name"],
                    "assigned_by": assigned_by,
                    "joined_at": now_iso(),
                }
            operation["members"] = list(operation_members.values())
            return list(operation_members.values())

    async def close_operation(
        self,
        operation_id: str,
        summary: str,
        outcome: str,
        closed_by: str,
    ) -> dict | None:
        async with self.lock:
            operation = self.operations.get(operation_id)
            if operation is None:
                return None

            operation["status"] = "closed"
            operation["closed_by"] = closed_by
            operation["closed_at"] = now_iso()
            operation["closing_summary"] = summary
            operation["outcome"] = outcome
            occurrence = self.occurrences.get(operation["occurrence_id"])
            if occurrence is not None:
                occurrence["status"] = "closed"
            self.status_events.setdefault(operation_id, []).append(
                {
                    "operation_id": operation_id,
                    "status": "closed",
                    "username": closed_by,
                    "note": f"{outcome}: {summary}",
                    "created_at": now_iso(),
                }
            )
            operation["members"] = list(self.members.get(operation_id, {}).values())
            operation["occurrence"] = occurrence
            return dict(operation)

    async def list_operations(
        self,
        status: str | None = None,
        base_id: str | None = None,
    ) -> list[dict]:
        async with self.lock:
            operations = [awaitable_copy_operation(item, self) for item in self.operations.values()]

        if status:
            operations = [operation for operation in operations if operation["status"] == status]
        if base_id:
            operations = [operation for operation in operations if operation["base_id"] == base_id]

        return sorted(operations, key=lambda item: item["created_at"], reverse=True)

    async def get_operation(self, operation_id: str) -> dict | None:
        async with self.lock:
            operation = self.operations.get(operation_id)
            if operation is None:
                return None
            return awaitable_copy_operation(operation, self)

    async def get_operation_by_channel(self, channel_id: str) -> dict | None:
        async with self.lock:
            for operation in self.operations.values():
                if operation["channel_id"] == channel_id:
                    return awaitable_copy_operation(operation, self)
        return None

    async def get_operation_audit(self, operation_id: str, messages: list[dict]) -> dict | None:
        operation = await self.get_operation(operation_id)
        if operation is None:
            return None
        async with self.lock:
            events = list(self.status_events.get(operation_id, []))
        return {
            "operation": operation,
            "messages": messages,
            "status_events": events,
        }


def awaitable_copy_operation(operation: dict, repository: InMemoryDomainRepository) -> dict:
    copied = dict(operation)
    if copied.get("status") == "closed" and not copied.get("outcome"):
        copied["outcome"] = "success"
    copied["occurrence"] = dict(repository.occurrences.get(operation["occurrence_id"], {}))
    copied["members"] = list(repository.members.get(operation["id"], {}).values())
    return copied


class PostgresDomainRepository:
    def __init__(self, database_url: str):
        from app.database import (
            create_bases_table,
            create_base_coverage_cities_table,
            create_occurrences_table,
            create_operation_members_table,
            create_operation_status_events_table,
            create_operations_table,
            create_operator_functions_table,
            create_operator_profiles_table,
        )
        from sqlalchemy.ext.asyncio import create_async_engine

        self.engine = create_async_engine(database_url)
        self.bases = create_bases_table()
        self.coverage_cities = create_base_coverage_cities_table()
        self.functions = create_operator_functions_table()
        self.profiles = create_operator_profiles_table()
        self.occurrences = create_occurrences_table()
        self.operations = create_operations_table()
        self.members = create_operation_members_table()
        self.status_events = create_operation_status_events_table()

    async def init_schema(self):
        from app.database import metadata

        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.exec_driver_sql("ALTER TABLE bases ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION")
            await connection.exec_driver_sql("ALTER TABLE bases ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION")
            await connection.exec_driver_sql("ALTER TABLE operator_profiles ADD COLUMN IF NOT EXISTS full_name VARCHAR(160)")
            await connection.exec_driver_sql("ALTER TABLE operator_profiles ADD COLUMN IF NOT EXISTS callsign VARCHAR(40)")
            await connection.exec_driver_sql("ALTER TABLE operator_profiles ADD COLUMN IF NOT EXISTS connection_status VARCHAR(40) DEFAULT 'offline'")
            await connection.exec_driver_sql("ALTER TABLE operator_profiles ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE")
            await connection.exec_driver_sql(
                "ALTER TABLE operations ADD COLUMN IF NOT EXISTS outcome VARCHAR(40)"
            )
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
                        latitude=DEFAULT_BASE["latitude"],
                        longitude=DEFAULT_BASE["longitude"],
                    )
                )
            elif invalid_coordinate(existing_base.get("latitude"), existing_base.get("longitude")):
                await connection.execute(
                    self.bases.update()
                    .where(self.bases.c.id == DEFAULT_BASE["id"])
                    .values(
                        latitude=DEFAULT_BASE["latitude"],
                        longitude=DEFAULT_BASE["longitude"],
                    )
                )
            existing_coverage = await self._get_coverage_cities(connection, DEFAULT_BASE["id"])
            if not existing_coverage:
                await self._replace_coverage_cities(
                    connection,
                    DEFAULT_BASE["id"],
                    DEFAULT_BASE["coverage_cities"],
                )
            for function in DEFAULT_FUNCTIONS:
                existing_function = await connection.execute(
                    self.functions.select().where(self.functions.c.id == function["id"])
                )
                if existing_function.mappings().one_or_none() is None:
                    await connection.execute(self.functions.insert().values(**function))

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
            result = await connection.execute(self.bases.delete().where(self.bases.c.id == base_id))
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

    async def list_functions(self) -> list[dict]:
        from sqlalchemy import select

        async with self.engine.connect() as connection:
            result = await connection.execute(select(self.functions).order_by(self.functions.c.label))
            rows = result.mappings().all()
        return [dict(row) for row in rows]

    async def create_function(self, data: dict) -> dict:
        values = {"id": data["id"].strip(), "label": data["label"].strip()}
        async with self.engine.begin() as connection:
            await connection.execute(self.functions.insert().values(**values))
        return values

    async def update_function(self, function_id: str, data: dict) -> dict | None:
        from sqlalchemy import update

        values = {"label": data["label"].strip()}
        async with self.engine.begin() as connection:
            result = await connection.execute(
                update(self.functions).where(self.functions.c.id == function_id).values(**values)
            )
        if result.rowcount == 0:
            return None
        return {"id": function_id, **values}

    async def delete_function(self, function_id: str) -> bool:
        async with self.engine.begin() as connection:
            result = await connection.execute(
                self.functions.delete().where(self.functions.c.id == function_id)
            )
        return result.rowcount > 0

    async def get_profile(self, username: str) -> dict | None:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                self.profiles.select().where(self.profiles.c.username == username)
            )
            row = result.mappings().one_or_none()
        return self._profile_dict(row) if row else None

    async def upsert_profile(self, username: str, data: dict) -> dict:
        from sqlalchemy.dialects.postgresql import insert

        full_name = (data.get("full_name") or data["operational_name"]).strip()
        callsign_base = (data.get("callsign") or derive_callsign_base(full_name)).strip().lower()
        callsign = await self._unique_callsign(username, callsign_base)
        values = {
            "username": username,
            "full_name": full_name,
            "callsign": callsign,
            "operational_name": data["operational_name"].strip(),
            "base_id": data["base_id"].strip(),
            "function": data["function"].strip(),
            "contact": data["contact"].strip(),
            "status": data["status"].strip(),
            "connection_status": data.get("connection_status", "offline"),
            "last_seen_at": data.get("last_seen_at"),
            "skills": serialize_skills(data.get("skills", [])),
            "updated_at": datetime.now(timezone.utc),
        }
        statement = insert(self.profiles).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[self.profiles.c.username],
            set_={
                "full_name": values["full_name"],
                "callsign": values["callsign"],
                "operational_name": values["operational_name"],
                "base_id": values["base_id"],
                "function": values["function"],
                "contact": values["contact"],
                "status": values["status"],
                "connection_status": values["connection_status"],
                "last_seen_at": values["last_seen_at"],
                "skills": values["skills"],
                "updated_at": values["updated_at"],
            },
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)
        return await self.get_profile(username) or {}

    async def update_presence(
        self,
        username: str,
        connection_status: str,
        last_seen_at: str | None = None,
    ) -> dict | None:
        from sqlalchemy import update

        values = {
            "connection_status": connection_status,
            "updated_at": datetime.now(timezone.utc),
        }
        if last_seen_at is not None:
            values["last_seen_at"] = datetime.fromisoformat(last_seen_at)
        async with self.engine.begin() as connection:
            result = await connection.execute(
                update(self.profiles)
                .where(self.profiles.c.username == username)
                .values(**values)
            )
        if result.rowcount == 0:
            return None
        return await self.get_profile(username)

    async def list_operator_profiles(
        self,
        base_id: str | None = None,
        status: str | None = None,
        skill: str | None = None,
    ) -> list[dict]:
        from sqlalchemy import select

        query = select(self.profiles)
        if base_id:
            query = query.where(self.profiles.c.base_id == base_id)
        if status:
            query = query.where(self.profiles.c.status == status)
        if skill:
            query = query.where(self.profiles.c.skills.ilike(f"%{skill}%"))
        query = query.order_by(self.profiles.c.operational_name)
        async with self.engine.connect() as connection:
            result = await connection.execute(query)
            rows = result.mappings().all()
        return [self._profile_dict(row) for row in rows]

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
        return await self._get_occurrence(occurrence["id"]) or occurrence

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
        return [self._row_dict(row) for row in rows]

    async def create_operation(
        self,
        occurrence: dict,
        member_users: list[dict],
        created_by: str,
    ) -> dict:
        operation_id = f"op-{uuid4().hex[:10]}"
        operation = {
            "id": operation_id,
            "occurrence_id": occurrence["id"],
            "base_id": occurrence["base_id"],
            "channel_id": f"operacao:{operation_id}",
            "status": "active",
            "created_by": created_by,
        }
        async with self.engine.begin() as connection:
            await connection.execute(self.operations.insert().values(**operation))
            await connection.execute(
                self.status_events.insert().values(
                    operation_id=operation_id,
                    status="active",
                    username=created_by,
                    note="Operacao criada.",
                )
            )
        await self.add_operation_members(operation_id, member_users, created_by)
        return await self.get_operation(operation_id) or operation

    async def add_operation_members(
        self,
        operation_id: str,
        member_users: list[dict],
        assigned_by: str,
    ) -> list[dict] | None:
        from sqlalchemy.dialects.postgresql import insert

        operation = await self.get_operation(operation_id)
        if operation is None:
            return None
        if operation["status"] == "closed":
            return operation["members"]

        async with self.engine.begin() as connection:
            for user in member_users:
                statement = insert(self.members).values(
                    operation_id=operation_id,
                    username=user["username"],
                    display_name=user["display_name"],
                    assigned_by=assigned_by,
                )
                statement = statement.on_conflict_do_nothing(
                    index_elements=[self.members.c.operation_id, self.members.c.username]
                )
                await connection.execute(statement)
        operation = await self.get_operation(operation_id)
        return operation["members"] if operation else None

    async def close_operation(
        self,
        operation_id: str,
        summary: str,
        outcome: str,
        closed_by: str,
    ) -> dict | None:
        from sqlalchemy import update

        operation = await self.get_operation(operation_id)
        if operation is None:
            return None

        async with self.engine.begin() as connection:
            await connection.execute(
                update(self.operations)
                .where(self.operations.c.id == operation_id)
                .values(
                    status="closed",
                    closed_by=closed_by,
                    closed_at=datetime.now(timezone.utc),
                    closing_summary=summary,
                    outcome=outcome,
                )
            )
            await connection.execute(
                update(self.occurrences)
                .where(self.occurrences.c.id == operation["occurrence_id"])
                .values(status="closed")
            )
            await connection.execute(
                self.status_events.insert().values(
                    operation_id=operation_id,
                    status="closed",
                    username=closed_by,
                    note=f"{outcome}: {summary}",
                )
            )
        return await self.get_operation(operation_id)

    async def list_operations(
        self,
        status: str | None = None,
        base_id: str | None = None,
    ) -> list[dict]:
        from sqlalchemy import desc, select

        query = select(self.operations)
        if status:
            query = query.where(self.operations.c.status == status)
        if base_id:
            query = query.where(self.operations.c.base_id == base_id)
        query = query.order_by(desc(self.operations.c.created_at))
        async with self.engine.connect() as connection:
            result = await connection.execute(query)
            rows = result.mappings().all()
        operations = []
        for row in rows:
            operation = await self.get_operation(row["id"])
            if operation:
                operations.append(operation)
        return operations

    async def get_operation(self, operation_id: str) -> dict | None:
        operation = await self._get_operation_row(operation_id)
        if operation is None:
            return None
        operation["occurrence"] = await self._get_occurrence(operation["occurrence_id"])
        operation["members"] = await self._get_members(operation_id)
        return operation

    async def get_operation_by_channel(self, channel_id: str) -> dict | None:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                self.operations.select().where(self.operations.c.channel_id == channel_id)
            )
            row = result.mappings().one_or_none()
        if row is None:
            return None
        return await self.get_operation(row["id"])

    async def get_operation_audit(self, operation_id: str, messages: list[dict]) -> dict | None:
        operation = await self.get_operation(operation_id)
        if operation is None:
            return None
        async with self.engine.connect() as connection:
            result = await connection.execute(
                self.status_events.select()
                .where(self.status_events.c.operation_id == operation_id)
                .order_by(self.status_events.c.created_at)
            )
            events = [self._row_dict(row) for row in result.mappings().all()]
        return {
            "operation": operation,
            "messages": messages,
            "status_events": events,
        }

    async def _get_operation_row(self, operation_id: str) -> dict | None:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                self.operations.select().where(self.operations.c.id == operation_id)
            )
            row = result.mappings().one_or_none()
        operation = self._row_dict(row) if row else None
        if operation and operation.get("status") == "closed" and not operation.get("outcome"):
            operation["outcome"] = "success"
        return operation

    async def _get_occurrence(self, occurrence_id: str) -> dict | None:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                self.occurrences.select().where(self.occurrences.c.id == occurrence_id)
            )
            row = result.mappings().one_or_none()
        return self._row_dict(row) if row else None

    async def _get_members(self, operation_id: str) -> list[dict]:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                self.members.select()
                .where(self.members.c.operation_id == operation_id)
                .order_by(self.members.c.display_name)
            )
            rows = result.mappings().all()
        return [self._row_dict(row) for row in rows]

    async def _unique_callsign(self, username: str, base: str) -> str:
        from sqlalchemy import select

        candidate = base or "op"
        suffix = 1
        async with self.engine.connect() as connection:
            while True:
                result = await connection.execute(
                    select(self.profiles.c.username).where(
                        self.profiles.c.callsign == candidate,
                        self.profiles.c.username != username,
                    )
                )
                if result.first() is None:
                    return candidate
                suffix += 1
                candidate = f"{base}{suffix}"

    def _profile_dict(self, row) -> dict:
        profile = self._row_dict(row)
        profile["skills"] = parse_skills(profile.get("skills", ""))
        if not profile.get("full_name"):
            profile["full_name"] = profile.get("operational_name", "")
        if not profile.get("callsign"):
            profile["callsign"] = derive_callsign_base(profile["full_name"])
        profile["display_name"] = derive_display_name(profile["full_name"])
        profile["connection_status"] = profile.get("connection_status") or "offline"
        return profile

    def _row_dict(self, row) -> dict:
        data = dict(row)
        for key, value in list(data.items()):
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data
