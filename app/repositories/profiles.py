import asyncio
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncEngine

from app.repositories._utils import (
    derive_callsign_base,
    derive_display_name,
    parse_skills,
    row_to_dict,
    serialize_skills,
)


class ProfileRepository(Protocol):
    async def init_schema(self):
        ...

    async def close(self):
        ...

    async def get_profile(self, username: str) -> dict | None:
        ...

    async def delete_profile(self, username: str) -> bool:
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryProfileRepository:
    def __init__(self):
        self.profiles: dict[str, dict] = {}
        self.lock = asyncio.Lock()

    async def init_schema(self):
        return None

    async def close(self):
        return None

    async def get_profile(self, username: str) -> dict | None:
        async with self.lock:
            profile = self.profiles.get(username)
            return self._profile_dict(profile) if profile else None

    async def delete_profile(self, username: str) -> bool:
        async with self.lock:
            return self.profiles.pop(username, None) is not None

    async def upsert_profile(self, username: str, data: dict) -> dict:
        full_name = (data.get("full_name") or data["operational_name"]).strip()
        callsign = (data.get("callsign") or derive_callsign_base(full_name)).strip().lower()
        profile = {
            "username": username,
            "full_name": full_name,
            "callsign": callsign,
            "operational_name": data["operational_name"].strip(),
            "base_id": data["base_id"].strip(),
            "function": (data.get("function") or "").strip(),
            "contact": data["contact"].strip(),
            "email": (data.get("email") or "").strip() or None,
            "status": data["status"].strip(),
            "connection_status": data.get("connection_status", "offline"),
            "last_seen_at": data.get("last_seen_at"),
            "skills": list(data.get("skills", [])),
            "updated_at": _now_iso(),
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
            profile["updated_at"] = _now_iso()
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
            profiles = [p for p in profiles if p["base_id"] == base_id]
        if status:
            profiles = [p for p in profiles if p["status"] == status]
        if skill:
            profiles = [
                p for p in profiles
                if skill.lower() in [s.lower() for s in p["skills"]]
            ]
        return sorted(
            [self._profile_dict(p) for p in profiles],
            key=lambda p: p["operational_name"],
        )

    def _profile_dict(self, profile: dict) -> dict:
        data = dict(profile)
        data["full_name"] = data.get("full_name") or data.get("operational_name", "")
        data["display_name"] = derive_display_name(data["full_name"])
        data["callsign"] = data.get("callsign") or derive_callsign_base(data["full_name"])
        data["connection_status"] = data.get("connection_status") or "offline"
        return data


class PostgresProfileRepository:
    def __init__(self, engine: AsyncEngine):
        from app.infra.db.tables import create_operator_profiles_table

        self.engine = engine
        self.profiles = create_operator_profiles_table()

    async def init_schema(self):
        from app.infra.db.tables import metadata

        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.exec_driver_sql("ALTER TABLE operator_profiles ADD COLUMN IF NOT EXISTS full_name VARCHAR(160)")
            await connection.exec_driver_sql("ALTER TABLE operator_profiles ADD COLUMN IF NOT EXISTS callsign VARCHAR(40)")
            await connection.exec_driver_sql("ALTER TABLE operator_profiles ADD COLUMN IF NOT EXISTS email VARCHAR(160)")
            await connection.exec_driver_sql("ALTER TABLE operator_profiles ADD COLUMN IF NOT EXISTS connection_status VARCHAR(40) DEFAULT 'offline'")
            await connection.exec_driver_sql("ALTER TABLE operator_profiles ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE")

    async def close(self):
        await self.engine.dispose()

    async def get_profile(self, username: str) -> dict | None:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                self.profiles.select().where(self.profiles.c.username == username)
            )
            row = result.mappings().one_or_none()
        return self._profile_dict(row_to_dict(row)) if row else None

    async def delete_profile(self, username: str) -> bool:
        async with self.engine.begin() as connection:
            result = await connection.execute(
                self.profiles.delete().where(self.profiles.c.username == username)
            )
        return result.rowcount > 0

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
            "function": (data.get("function") or "").strip(),
            "contact": data["contact"].strip(),
            "email": (data.get("email") or "").strip() or None,
            "status": data["status"].strip(),
            "connection_status": data.get("connection_status", "offline"),
            "last_seen_at": data.get("last_seen_at"),
            "skills": serialize_skills(data.get("skills", [])),
            "updated_at": datetime.now(timezone.utc),
        }
        statement = insert(self.profiles).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[self.profiles.c.username],
            set_={k: values[k] for k in values if k != "username"},
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

        values = {"connection_status": connection_status, "updated_at": datetime.now(timezone.utc)}
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
        return [self._profile_dict(row_to_dict(row)) for row in rows]

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

    def _profile_dict(self, profile: dict) -> dict:
        profile["skills"] = parse_skills(profile.get("skills") or "")
        if not profile.get("full_name"):
            profile["full_name"] = profile.get("operational_name", "")
        if not profile.get("callsign"):
            profile["callsign"] = derive_callsign_base(profile["full_name"])
        profile["display_name"] = derive_display_name(profile["full_name"])
        profile["connection_status"] = profile.get("connection_status") or "offline"
        return profile
