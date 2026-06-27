import asyncio
from typing import Protocol

from sqlalchemy.exc import IntegrityError

from app.auth import ALLOWED_ROLES, ROLE_ADMIN, ROLE_OPERADOR, hash_password


class DuplicateUserError(Exception):
    pass


class InvalidRoleError(Exception):
    pass


class UserRepository(Protocol):
    async def init_schema(self):
        ...

    async def create_user(
        self,
        username: str,
        password: str,
        display_name: str | None = None,
        role: str = ROLE_OPERADOR,
        base_id: str | None = None,
        uf_scope: str | None = None,
    ) -> dict:
        ...

    async def get_by_username(self, username: str) -> dict | None:
        ...

    async def list_users(self) -> list[dict]:
        ...

    async def update_role(
        self,
        username: str,
        role: str,
        base_id: str | None = None,
        uf_scope: str | None = None,
    ) -> dict | None:
        ...

    async def update_identity(
        self,
        username: str,
        display_name: str | None = None,
        base_id: str | None = None,
        uf_scope: str | None = None,
    ) -> dict | None:
        ...

    async def has_admin(self) -> bool:
        ...

    async def close(self):
        ...


class InMemoryUserRepository:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.lock = asyncio.Lock()

    async def init_schema(self):
        return None

    async def create_user(
        self,
        username: str,
        password: str,
        display_name: str | None = None,
        role: str = ROLE_OPERADOR,
        base_id: str | None = None,
        uf_scope: str | None = None,
    ) -> dict:
        if role not in ALLOWED_ROLES:
            raise InvalidRoleError(role)
        normalized_username = username.strip()
        async with self.lock:
            if normalized_username in self.users:
                raise DuplicateUserError(normalized_username)

            user = {
                "username": normalized_username,
                "display_name": (display_name or normalized_username).strip(),
                "password_hash": hash_password(password),
                "role": role,
                "base_id": base_id.strip() if base_id else None,
                "uf_scope": uf_scope.strip().upper() if uf_scope else None,
            }
            self.users[normalized_username] = user
            return dict(user)

    async def get_by_username(self, username: str) -> dict | None:
        async with self.lock:
            user = self.users.get(username.strip())
            return dict(user) if user else None

    async def list_users(self) -> list[dict]:
        async with self.lock:
            return [
                dict(user)
                for user in sorted(
                    self.users.values(),
                    key=lambda item: item["username"],
                )
            ]

    async def update_role(
        self,
        username: str,
        role: str,
        base_id: str | None = None,
        uf_scope: str | None = None,
    ) -> dict | None:
        if role not in ALLOWED_ROLES:
            raise InvalidRoleError(role)

        async with self.lock:
            user = self.users.get(username.strip())

            if user is None:
                return None

            user["role"] = role
            user["base_id"] = base_id.strip() if base_id else None
            user["uf_scope"] = uf_scope.strip().upper() if uf_scope else None
            return dict(user)

    async def update_identity(
        self,
        username: str,
        display_name: str | None = None,
        base_id: str | None = None,
        uf_scope: str | None = None,
    ) -> dict | None:
        async with self.lock:
            user = self.users.get(username.strip())
            if user is None:
                return None
            if display_name is not None:
                user["display_name"] = display_name.strip()
            if base_id is not None:
                user["base_id"] = base_id.strip() or None
            if uf_scope is not None:
                user["uf_scope"] = uf_scope.strip().upper() or None
            return dict(user)

    async def has_admin(self) -> bool:
        async with self.lock:
            return any(user["role"] == ROLE_ADMIN for user in self.users.values())

    async def close(self):
        return None


class PostgresUserRepository:
    def __init__(self, database_url: str):
        from app.database import create_users_table
        from sqlalchemy.ext.asyncio import create_async_engine

        self.engine = create_async_engine(database_url)
        self.users = create_users_table()

    async def init_schema(self):
        from app.database import metadata

        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS base_id VARCHAR(80)")
            await connection.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS uf_scope VARCHAR(2)")

    async def create_user(
        self,
        username: str,
        password: str,
        display_name: str | None = None,
        role: str = ROLE_OPERADOR,
        base_id: str | None = None,
        uf_scope: str | None = None,
    ) -> dict:
        from sqlalchemy import text

        if role not in ALLOWED_ROLES:
            raise InvalidRoleError(role)

        normalized_username = username.strip()
        normalized_display_name = (display_name or normalized_username).strip()
        normalized_base_id = base_id.strip() if base_id else None
        normalized_uf_scope = uf_scope.strip().upper() if uf_scope else None

        async with self.engine.begin() as connection:
            await connection.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS base_id VARCHAR(80)")
            await connection.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS uf_scope VARCHAR(2)")
            await connection.execute(text("LOCK TABLE users IN EXCLUSIVE MODE"))

            insert_statement = (
                self.users.insert()
                .values(
                    username=normalized_username,
                    display_name=normalized_display_name,
                    password_hash=hash_password(password),
                    role=role,
                    base_id=normalized_base_id,
                    uf_scope=normalized_uf_scope,
                )
                .returning(
                    self.users.c.username,
                    self.users.c.display_name,
                    self.users.c.password_hash,
                    self.users.c.role,
                    self.users.c.base_id,
                    self.users.c.uf_scope,
                )
            )

            try:
                result = await connection.execute(insert_statement)
            except IntegrityError as error:
                raise DuplicateUserError(normalized_username) from error

            return dict(result.mappings().one())

    async def get_by_username(self, username: str) -> dict | None:
        from sqlalchemy import select

        query = select(
            self.users.c.username,
            self.users.c.display_name,
            self.users.c.password_hash,
            self.users.c.role,
            self.users.c.base_id,
            self.users.c.uf_scope,
        ).where(self.users.c.username == username.strip())

        async with self.engine.connect() as connection:
            result = await connection.execute(query)
            row = result.mappings().one_or_none()

        return dict(row) if row else None

    async def list_users(self) -> list[dict]:
        from sqlalchemy import select

        query = select(
            self.users.c.username,
            self.users.c.display_name,
            self.users.c.password_hash,
            self.users.c.role,
            self.users.c.base_id,
            self.users.c.uf_scope,
        ).order_by(self.users.c.username)

        async with self.engine.connect() as connection:
            result = await connection.execute(query)
            rows = result.mappings().all()

        return [dict(row) for row in rows]

    async def update_role(
        self,
        username: str,
        role: str,
        base_id: str | None = None,
        uf_scope: str | None = None,
    ) -> dict | None:
        if role not in ALLOWED_ROLES:
            raise InvalidRoleError(role)

        update_statement = (
            self.users.update()
            .where(self.users.c.username == username.strip())
            .values(
                role=role,
                base_id=base_id.strip() if base_id else None,
                uf_scope=uf_scope.strip().upper() if uf_scope else None,
            )
            .returning(
                self.users.c.username,
                self.users.c.display_name,
                self.users.c.password_hash,
                self.users.c.role,
                self.users.c.base_id,
                self.users.c.uf_scope,
            )
        )

        async with self.engine.begin() as connection:
            result = await connection.execute(update_statement)
            row = result.mappings().one_or_none()

        return dict(row) if row else None

    async def update_identity(
        self,
        username: str,
        display_name: str | None = None,
        base_id: str | None = None,
        uf_scope: str | None = None,
    ) -> dict | None:
        values = {}
        if display_name is not None:
            values["display_name"] = display_name.strip()
        if base_id is not None:
            values["base_id"] = base_id.strip() or None
        if uf_scope is not None:
            values["uf_scope"] = uf_scope.strip().upper() or None
        if not values:
            return await self.get_by_username(username)

        update_statement = (
            self.users.update()
            .where(self.users.c.username == username.strip())
            .values(**values)
            .returning(
                self.users.c.username,
                self.users.c.display_name,
                self.users.c.password_hash,
                self.users.c.role,
                self.users.c.base_id,
                self.users.c.uf_scope,
            )
        )
        async with self.engine.begin() as connection:
            result = await connection.execute(update_statement)
            row = result.mappings().one_or_none()
        return dict(row) if row else None

    async def has_admin(self) -> bool:
        from sqlalchemy import func, select

        async with self.engine.connect() as connection:
            result = await connection.execute(
                select(func.count()).select_from(self.users).where(self.users.c.role == ROLE_ADMIN)
            )
        return result.scalar_one() > 0

    async def close(self):
        await self.engine.dispose()
