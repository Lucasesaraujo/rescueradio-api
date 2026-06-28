import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine

from app.domain.auth import ALLOWED_ROLES, ROLE_COMANDANTE, ROLE_OPERADOR


class InvalidInviteError(Exception):
    pass


class InviteRepository(Protocol):
    async def init_schema(self):
        ...

    async def close(self):
        ...

    async def create_invite(self, data: dict, created_by: str) -> dict:
        ...

    async def list_invites(self) -> list[dict]:
        ...

    async def revoke_invite(self, invite_id: str) -> bool:
        ...

    async def consume_invite(self, code: str, used_by: str) -> dict:
        ...


def hash_invite_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def public_invite(invite: dict, code: str | None = None) -> dict:
    data = {k: v for k, v in invite.items() if k != "code_hash"}
    if code is not None:
        data["code"] = code
    return data


def normalize_invite_data(data: dict) -> dict:
    role = data.get("role") or ROLE_OPERADOR
    if role not in ALLOWED_ROLES:
        role = ROLE_OPERADOR
    base_id = (data.get("base_id") or "").strip() or None
    uf_scope = (data.get("uf_scope") or "").strip().upper() or None
    if role == ROLE_OPERADOR and not base_id:
        raise InvalidInviteError()
    if role == ROLE_COMANDANTE and not uf_scope:
        raise InvalidInviteError()
    expires_in_hours = data.get("expires_in_hours")
    expires_at = data.get("expires_at")
    if expires_at is None and expires_in_hours:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=int(expires_in_hours))
    return {"base_id": base_id, "uf_scope": uf_scope, "role": role, "expires_at": expires_at}


def invite_is_active(invite: dict) -> bool:
    if invite.get("used_at") or invite.get("revoked_at"):
        return False
    expires_at = invite.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    return expires_at is None or expires_at > datetime.now(timezone.utc)


class InMemoryInviteRepository:
    def __init__(self):
        self.invites: dict[str, dict] = {}
        self.lock = asyncio.Lock()

    async def init_schema(self):
        return None

    async def close(self):
        return None

    async def create_invite(self, data: dict, created_by: str) -> dict:
        code = secrets.token_urlsafe(10)
        values = normalize_invite_data(data)
        invite = {
            "id": f"inv-{uuid4().hex[:10]}",
            "code_hash": hash_invite_code(code),
            **values,
            "used_by": None,
            "used_at": None,
            "revoked_at": None,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        async with self.lock:
            self.invites[invite["id"]] = invite
        return public_invite(invite, code)

    async def list_invites(self) -> list[dict]:
        async with self.lock:
            invites = list(self.invites.values())
        return [
            public_invite(invite)
            for invite in sorted(invites, key=lambda i: i["created_at"], reverse=True)
        ]

    async def revoke_invite(self, invite_id: str) -> bool:
        async with self.lock:
            invite = self.invites.get(invite_id)
            if invite is None:
                return False
            invite["revoked_at"] = datetime.now(timezone.utc).isoformat()
            return True

    async def consume_invite(self, code: str, used_by: str) -> dict:
        code_hash = hash_invite_code(code)
        async with self.lock:
            invite = next(
                (item for item in self.invites.values() if item["code_hash"] == code_hash),
                None,
            )
            if invite is None or not invite_is_active(invite):
                raise InvalidInviteError()
            invite["used_by"] = used_by
            invite["used_at"] = datetime.now(timezone.utc).isoformat()
            return public_invite(invite)


class PostgresInviteRepository:
    def __init__(self, engine: AsyncEngine):
        from app.infra.db.tables import create_invites_table

        self.engine = engine
        self.invites = create_invites_table()

    async def init_schema(self):
        from app.infra.db.tables import metadata

        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.exec_driver_sql("ALTER TABLE invites ALTER COLUMN base_id DROP NOT NULL")
            await connection.exec_driver_sql("ALTER TABLE invites ADD COLUMN IF NOT EXISTS uf_scope VARCHAR(2)")

    async def close(self):
        await self.engine.dispose()

    async def create_invite(self, data: dict, created_by: str) -> dict:
        code = secrets.token_urlsafe(10)
        values = normalize_invite_data(data)
        invite = {
            "id": f"inv-{uuid4().hex[:10]}",
            "code_hash": hash_invite_code(code),
            **values,
            "created_by": created_by,
        }
        async with self.engine.begin() as connection:
            await connection.execute(self.invites.insert().values(**invite))
        created = await self._get_invite(invite["id"])
        return public_invite(created or invite, code)

    async def list_invites(self) -> list[dict]:
        from sqlalchemy import desc, select

        async with self.engine.connect() as connection:
            result = await connection.execute(
                select(self.invites).order_by(desc(self.invites.c.created_at))
            )
            rows = result.mappings().all()
        return [public_invite(self._row_dict(row)) for row in rows]

    async def revoke_invite(self, invite_id: str) -> bool:
        from sqlalchemy import update

        async with self.engine.begin() as connection:
            result = await connection.execute(
                update(self.invites)
                .where(self.invites.c.id == invite_id)
                .values(revoked_at=datetime.now(timezone.utc))
            )
        return result.rowcount > 0

    async def consume_invite(self, code: str, used_by: str) -> dict:
        from sqlalchemy import update

        code_hash = hash_invite_code(code)
        async with self.engine.begin() as connection:
            result = await connection.execute(
                self.invites.select().where(self.invites.c.code_hash == code_hash)
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise InvalidInviteError()
            invite_dict = self._row_dict(row)
            if not invite_is_active(invite_dict):
                raise InvalidInviteError()
            await connection.execute(
                update(self.invites)
                .where(self.invites.c.id == invite_dict["id"])
                .values(used_by=used_by, used_at=datetime.now(timezone.utc))
            )
        invite_dict["used_by"] = used_by
        invite_dict["used_at"] = datetime.now(timezone.utc).isoformat()
        return public_invite(invite_dict)

    async def _get_invite(self, invite_id: str) -> dict | None:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                self.invites.select().where(self.invites.c.id == invite_id)
            )
            row = result.mappings().one_or_none()
        return self._row_dict(row) if row else None

    def _row_dict(self, row) -> dict:
        data = dict(row)
        for key, value in list(data.items()):
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data
