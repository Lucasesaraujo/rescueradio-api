import asyncio
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine

from app.repositories._utils import now_iso, row_to_dict
from app.repositories.occurrences import InMemoryOccurrenceRepository, OccurrenceRepository


class OperationRepository(Protocol):
    async def init_schema(self):
        ...

    async def close(self):
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


class InMemoryOperationRepository:
    def __init__(self, occurrence_repository: InMemoryOccurrenceRepository):
        self._occurrences = occurrence_repository
        self.operations: dict[str, dict] = {}
        self.members: dict[str, dict[str, dict]] = {}
        self.status_events: dict[str, list[dict]] = {}
        self.assignment_acks: set[tuple[str, str]] = set()
        self.lock = asyncio.Lock()

    async def init_schema(self):
        return None

    async def close(self):
        return None

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
        await self._occurrences.update_status(operation["occurrence_id"], "closed")
        operation["occurrence"] = await self._occurrences.get_occurrence(operation["occurrence_id"])
        return dict(operation)

    async def list_operations(
        self,
        status: str | None = None,
        base_id: str | None = None,
    ) -> list[dict]:
        async with self.lock:
            operations = [self._copy_operation(op) for op in self.operations.values()]
        if status:
            operations = [op for op in operations if op["status"] == status]
        if base_id:
            operations = [op for op in operations if op["base_id"] == base_id]
        for op in operations:
            op["occurrence"] = await self._occurrences.get_occurrence(op["occurrence_id"])
        return sorted(operations, key=lambda op: op["created_at"], reverse=True)

    async def get_operation(self, operation_id: str) -> dict | None:
        async with self.lock:
            operation = self.operations.get(operation_id)
            if operation is None:
                return None
            op = self._copy_operation(operation)
        op["occurrence"] = await self._occurrences.get_occurrence(op["occurrence_id"])
        return op

    async def get_operation_by_channel(self, channel_id: str) -> dict | None:
        async with self.lock:
            for operation in self.operations.values():
                if operation["channel_id"] == channel_id:
                    op = self._copy_operation(operation)
                    break
            else:
                return None
        op["occurrence"] = await self._occurrences.get_occurrence(op["occurrence_id"])
        return op

    async def get_operation_audit(self, operation_id: str, messages: list[dict]) -> dict | None:
        operation = await self.get_operation(operation_id)
        if operation is None:
            return None
        async with self.lock:
            events = list(self.status_events.get(operation_id, []))
        return {"operation": operation, "messages": messages, "status_events": events}

    async def acknowledge_assignment(self, operation_id: str, username: str) -> bool:
        async with self.lock:
            if operation_id not in self.operations:
                return False
            self.assignment_acks.add((operation_id, username))
            return True

    async def is_assignment_acknowledged(self, operation_id: str, username: str) -> bool:
        async with self.lock:
            return (operation_id, username) in self.assignment_acks

    def _copy_operation(self, operation: dict) -> dict:
        copied = dict(operation)
        if copied.get("status") == "closed" and not copied.get("outcome"):
            copied["outcome"] = "success"
        copied["members"] = list(self.members.get(operation["id"], {}).values())
        return copied


class PostgresOperationRepository:
    def __init__(self, engine: AsyncEngine):
        from app.infra.db.tables import (
            create_occurrences_table,
            create_operation_assignment_acks_table,
            create_operation_members_table,
            create_operation_status_events_table,
            create_operations_table,
        )

        self.engine = engine
        self.operations = create_operations_table()
        self.members = create_operation_members_table()
        self.assignment_acks = create_operation_assignment_acks_table()
        self.status_events = create_operation_status_events_table()
        self.occurrences = create_occurrences_table()

    async def init_schema(self):
        from app.infra.db.tables import metadata

        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.exec_driver_sql(
                "ALTER TABLE operations ADD COLUMN IF NOT EXISTS outcome VARCHAR(40)"
            )

    async def close(self):
        await self.engine.dispose()

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
            events = [row_to_dict(row) for row in result.mappings().all()]
        return {"operation": operation, "messages": messages, "status_events": events}

    async def acknowledge_assignment(self, operation_id: str, username: str) -> bool:
        from sqlalchemy.dialects.postgresql import insert

        if await self.get_operation(operation_id) is None:
            return False

        async with self.engine.begin() as connection:
            statement = insert(self.assignment_acks).values(
                operation_id=operation_id,
                username=username,
            )
            statement = statement.on_conflict_do_nothing(
                index_elements=[
                    self.assignment_acks.c.operation_id,
                    self.assignment_acks.c.username,
                ],
            )
            await connection.execute(statement)
        return True

    async def is_assignment_acknowledged(self, operation_id: str, username: str) -> bool:
        from sqlalchemy import select

        async with self.engine.connect() as connection:
            result = await connection.execute(
                select(self.assignment_acks.c.operation_id).where(
                    self.assignment_acks.c.operation_id == operation_id,
                    self.assignment_acks.c.username == username,
                )
            )
            return result.first() is not None

    async def _get_operation_row(self, operation_id: str) -> dict | None:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                self.operations.select().where(self.operations.c.id == operation_id)
            )
            row = result.mappings().one_or_none()
        if row is None:
            return None
        operation = row_to_dict(row)
        if operation.get("status") == "closed" and not operation.get("outcome"):
            operation["outcome"] = "success"
        return operation

    async def _get_occurrence(self, occurrence_id: str) -> dict | None:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                self.occurrences.select().where(self.occurrences.c.id == occurrence_id)
            )
            row = result.mappings().one_or_none()
        return row_to_dict(row) if row else None

    async def _get_members(self, operation_id: str) -> list[dict]:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                self.members.select()
                .where(self.members.c.operation_id == operation_id)
                .order_by(self.members.c.display_name)
            )
            rows = result.mappings().all()
        return [row_to_dict(row) for row in rows]
