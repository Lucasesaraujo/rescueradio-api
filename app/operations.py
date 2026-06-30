from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncEngine

from app.repositories.bases import InMemoryBaseRepository, PostgresBaseRepository
from app.repositories.occurrences import InMemoryOccurrenceRepository, PostgresOccurrenceRepository
from app.repositories.operations import InMemoryOperationRepository, PostgresOperationRepository
from app.repositories.profiles import InMemoryProfileRepository, PostgresProfileRepository


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

    async def acknowledge_assignment(self, operation_id: str, username: str) -> bool:
        ...

    async def is_assignment_acknowledged(self, operation_id: str, username: str) -> bool:
        ...


class InMemoryDomainRepository:
    def __init__(self):
        self._bases = InMemoryBaseRepository()
        self._profiles = InMemoryProfileRepository()
        self._occurrences = InMemoryOccurrenceRepository()
        self._operations = InMemoryOperationRepository(self._occurrences)

    async def init_schema(self):
        await self._bases.init_schema()
        await self._profiles.init_schema()
        await self._occurrences.init_schema()
        await self._operations.init_schema()

    async def close(self):
        return None

    async def list_bases(self) -> list[dict]:
        return await self._bases.list_bases()

    async def create_base(self, data: dict) -> dict:
        return await self._bases.create_base(data)

    async def update_base(self, base_id: str, data: dict) -> dict | None:
        return await self._bases.update_base(base_id, data)

    async def delete_base(self, base_id: str) -> bool:
        return await self._bases.delete_base(base_id)

    async def get_profile(self, username: str) -> dict | None:
        return await self._profiles.get_profile(username)

    async def delete_profile(self, username: str) -> bool:
        return await self._profiles.delete_profile(username)

    async def upsert_profile(self, username: str, data: dict) -> dict:
        return await self._profiles.upsert_profile(username, data)

    async def update_presence(
        self,
        username: str,
        connection_status: str,
        last_seen_at: str | None = None,
    ) -> dict | None:
        return await self._profiles.update_presence(username, connection_status, last_seen_at)

    async def list_operator_profiles(
        self,
        base_id: str | None = None,
        status: str | None = None,
        skill: str | None = None,
    ) -> list[dict]:
        return await self._profiles.list_operator_profiles(base_id, status, skill)

    async def create_occurrence(self, data: dict, created_by: str) -> dict:
        return await self._occurrences.create_occurrence(data, created_by)

    async def list_occurrences(
        self,
        status: str | None = None,
        base_id: str | None = None,
    ) -> list[dict]:
        return await self._occurrences.list_occurrences(status, base_id)

    async def create_operation(
        self,
        occurrence: dict,
        member_users: list[dict],
        created_by: str,
    ) -> dict:
        return await self._operations.create_operation(occurrence, member_users, created_by)

    async def add_operation_members(
        self,
        operation_id: str,
        member_users: list[dict],
        assigned_by: str,
    ) -> list[dict] | None:
        return await self._operations.add_operation_members(operation_id, member_users, assigned_by)

    async def close_operation(
        self,
        operation_id: str,
        summary: str,
        outcome: str,
        closed_by: str,
    ) -> dict | None:
        return await self._operations.close_operation(operation_id, summary, outcome, closed_by)

    async def list_operations(
        self,
        status: str | None = None,
        base_id: str | None = None,
    ) -> list[dict]:
        return await self._operations.list_operations(status, base_id)

    async def get_operation(self, operation_id: str) -> dict | None:
        return await self._operations.get_operation(operation_id)

    async def get_operation_by_channel(self, channel_id: str) -> dict | None:
        return await self._operations.get_operation_by_channel(channel_id)

    async def get_operation_audit(self, operation_id: str, messages: list[dict]) -> dict | None:
        return await self._operations.get_operation_audit(operation_id, messages)

    async def acknowledge_assignment(self, operation_id: str, username: str) -> bool:
        return await self._operations.acknowledge_assignment(operation_id, username)

    async def is_assignment_acknowledged(self, operation_id: str, username: str) -> bool:
        return await self._operations.is_assignment_acknowledged(operation_id, username)


class PostgresDomainRepository:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine
        self._bases = PostgresBaseRepository(engine)
        self._profiles = PostgresProfileRepository(engine)
        self._occurrences = PostgresOccurrenceRepository(engine)
        self._operations = PostgresOperationRepository(engine)

    async def init_schema(self):
        await self._bases.init_schema()
        await self._profiles.init_schema()
        await self._occurrences.init_schema()
        await self._operations.init_schema()

    async def close(self):
        await self._engine.dispose()

    async def list_bases(self) -> list[dict]:
        return await self._bases.list_bases()

    async def create_base(self, data: dict) -> dict:
        return await self._bases.create_base(data)

    async def update_base(self, base_id: str, data: dict) -> dict | None:
        return await self._bases.update_base(base_id, data)

    async def delete_base(self, base_id: str) -> bool:
        return await self._bases.delete_base(base_id)

    async def get_profile(self, username: str) -> dict | None:
        return await self._profiles.get_profile(username)

    async def delete_profile(self, username: str) -> bool:
        return await self._profiles.delete_profile(username)

    async def upsert_profile(self, username: str, data: dict) -> dict:
        return await self._profiles.upsert_profile(username, data)

    async def update_presence(
        self,
        username: str,
        connection_status: str,
        last_seen_at: str | None = None,
    ) -> dict | None:
        return await self._profiles.update_presence(username, connection_status, last_seen_at)

    async def list_operator_profiles(
        self,
        base_id: str | None = None,
        status: str | None = None,
        skill: str | None = None,
    ) -> list[dict]:
        return await self._profiles.list_operator_profiles(base_id, status, skill)

    async def create_occurrence(self, data: dict, created_by: str) -> dict:
        return await self._occurrences.create_occurrence(data, created_by)

    async def list_occurrences(
        self,
        status: str | None = None,
        base_id: str | None = None,
    ) -> list[dict]:
        return await self._occurrences.list_occurrences(status, base_id)

    async def create_operation(
        self,
        occurrence: dict,
        member_users: list[dict],
        created_by: str,
    ) -> dict:
        return await self._operations.create_operation(occurrence, member_users, created_by)

    async def add_operation_members(
        self,
        operation_id: str,
        member_users: list[dict],
        assigned_by: str,
    ) -> list[dict] | None:
        return await self._operations.add_operation_members(operation_id, member_users, assigned_by)

    async def close_operation(
        self,
        operation_id: str,
        summary: str,
        outcome: str,
        closed_by: str,
    ) -> dict | None:
        return await self._operations.close_operation(operation_id, summary, outcome, closed_by)

    async def list_operations(
        self,
        status: str | None = None,
        base_id: str | None = None,
    ) -> list[dict]:
        return await self._operations.list_operations(status, base_id)

    async def get_operation(self, operation_id: str) -> dict | None:
        return await self._operations.get_operation(operation_id)

    async def get_operation_by_channel(self, channel_id: str) -> dict | None:
        return await self._operations.get_operation_by_channel(channel_id)

    async def get_operation_audit(self, operation_id: str, messages: list[dict]) -> dict | None:
        return await self._operations.get_operation_audit(operation_id, messages)

    async def acknowledge_assignment(self, operation_id: str, username: str) -> bool:
        return await self._operations.acknowledge_assignment(operation_id, username)

    async def is_assignment_acknowledged(self, operation_id: str, username: str) -> bool:
        return await self._operations.is_assignment_acknowledged(operation_id, username)
