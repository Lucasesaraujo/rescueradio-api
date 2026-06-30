from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.domain.auth import ROLE_ADMIN
from app.dependencies import (
    get_audit_publisher,
    get_current_user,
    get_domain_repository,
    get_message_repository,
    get_notification_manager,
    get_user_repository,
    require_base_access,
    require_members_in_user_base,
    require_role,
    users_from_usernames,
    visible_base_ids,
)
from app.domain.schemas import OperationCloseRequest, OperationCreateRequest, OperationMembersRequest

router = APIRouter(prefix="/operations", tags=["Operacoes"])


async def _notify_operation_assigned(
    operation: dict,
    member_users: list[dict],
    assigned_by: str,
    notification_manager,
):
    for member in member_users:
        await notification_manager.notify(
            member["username"],
            {
                "type": "OPERATION_ASSIGNED",
                "operation_id": operation["id"],
                "channel_id": operation["channel_id"],
                "title": operation.get("occurrence", {}).get("title") or operation["id"],
                "priority": operation.get("occurrence", {}).get("priority", "normal"),
                "base_id": operation["base_id"],
                "assigned_by": assigned_by,
                "created_at": operation.get("created_at") or datetime.now(timezone.utc).isoformat(),
            },
        )


@router.post("", status_code=201)
async def create_operation(
    request: OperationCreateRequest,
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
    user_repository=Depends(get_user_repository),
    audit_publisher=Depends(get_audit_publisher),
    notification_manager=Depends(get_notification_manager),
):
    require_role(current_user, {"admin", "comandante"})
    await require_base_access(current_user, request.occurrence.base_id, domain_repository)
    occurrence = await domain_repository.create_occurrence(
        request.occurrence.model_dump(),
        current_user["username"],
    )
    member_users = await users_from_usernames(request.member_usernames, user_repository)
    await require_members_in_user_base(current_user, member_users, domain_repository)
    operation = await domain_repository.create_operation(
        occurrence,
        member_users,
        current_user["username"],
    )
    await audit_publisher.publish(
        "operation_created",
        {
            "operation_id": operation["id"],
            "occurrence_id": occurrence["id"],
            "base_id": operation["base_id"],
            "members": [u["username"] for u in member_users],
            "created_by": current_user["username"],
        },
    )
    await _notify_operation_assigned(operation, member_users, current_user["username"], notification_manager)
    return operation


@router.get("")
async def list_operations(
    status: str | None = None,
    base_id: str | None = None,
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
):
    if current_user["role"] != ROLE_ADMIN:
        allowed = await visible_base_ids(current_user, domain_repository)
        operations = await domain_repository.list_operations(status, None)
        return [item for item in operations if item.get("base_id") in (allowed or set())]
    return await domain_repository.list_operations(status, base_id)


@router.get("/{operation_id}")
async def get_operation(
    operation_id: str,
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
):
    operation = await domain_repository.get_operation(operation_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="Operacao nao encontrada")
    await require_base_access(current_user, operation["base_id"], domain_repository)
    return operation


@router.post("/{operation_id}/members")
async def add_operation_members(
    operation_id: str,
    request: OperationMembersRequest,
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
    user_repository=Depends(get_user_repository),
    audit_publisher=Depends(get_audit_publisher),
    notification_manager=Depends(get_notification_manager),
):
    require_role(current_user, {"admin", "comandante"})
    operation = await domain_repository.get_operation(operation_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="Operacao nao encontrada")
    await require_base_access(current_user, operation["base_id"], domain_repository)
    member_users = await users_from_usernames(request.usernames, user_repository)
    await require_members_in_user_base(current_user, member_users, domain_repository)
    members = await domain_repository.add_operation_members(
        operation_id,
        member_users,
        current_user["username"],
    )
    if members is None:
        raise HTTPException(status_code=404, detail="Operacao nao encontrada")
    await audit_publisher.publish(
        "operation_members_added",
        {
            "operation_id": operation_id,
            "members": [u["username"] for u in member_users],
            "assigned_by": current_user["username"],
        },
    )
    operation = await domain_repository.get_operation(operation_id)
    if operation is not None:
        await _notify_operation_assigned(operation, member_users, current_user["username"], notification_manager)
    return members


@router.post("/{operation_id}/close")
async def close_operation(
    operation_id: str,
    request: OperationCloseRequest,
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
    audit_publisher=Depends(get_audit_publisher),
):
    require_role(current_user, {"admin", "comandante"})
    existing = await domain_repository.get_operation(operation_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Operacao nao encontrada")
    await require_base_access(current_user, existing["base_id"], domain_repository)
    operation = await domain_repository.close_operation(
        operation_id,
        request.summary,
        request.outcome,
        current_user["username"],
    )
    if operation is None:
        raise HTTPException(status_code=404, detail="Operacao nao encontrada")
    await audit_publisher.publish(
        "operation_closed",
        {"operation_id": operation_id, "closed_by": current_user["username"]},
    )
    return operation


@router.get("/{operation_id}/audit")
async def get_operation_audit(
    operation_id: str,
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
    message_repository=Depends(get_message_repository),
):
    operation = await domain_repository.get_operation(operation_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="Operacao nao encontrada")
    await require_base_access(current_user, operation["base_id"], domain_repository)
    messages = await message_repository.get_channel_messages(operation["channel_id"])
    return await domain_repository.get_operation_audit(operation_id, messages)


@router.get("/{operation_id}/assignment-ack")
async def get_assignment_ack(
    operation_id: str,
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
):
    operation = await domain_repository.get_operation(operation_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="Operacao nao encontrada")
    await require_base_access(current_user, operation["base_id"], domain_repository)
    acknowledged = await domain_repository.is_assignment_acknowledged(
        operation_id,
        current_user["username"],
    )
    return {"operation_id": operation_id, "acknowledged": acknowledged}


@router.post("/{operation_id}/assignment-ack")
async def acknowledge_assignment(
    operation_id: str,
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
):
    operation = await domain_repository.get_operation(operation_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="Operacao nao encontrada")
    await require_base_access(current_user, operation["base_id"], domain_repository)
    acknowledged = await domain_repository.acknowledge_assignment(
        operation_id,
        current_user["username"],
    )
    if not acknowledged:
        raise HTTPException(status_code=404, detail="Operacao nao encontrada")
    return {"operation_id": operation_id, "acknowledged": True}
