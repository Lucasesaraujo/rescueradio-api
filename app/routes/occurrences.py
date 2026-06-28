from fastapi import APIRouter, Depends

from app.domain.auth import ROLE_ADMIN
from app.dependencies import (
    get_audit_publisher,
    get_current_user,
    get_domain_repository,
    require_base_access,
    require_role,
    visible_base_ids,
)
from app.domain.schemas import OccurrenceCreateRequest

router = APIRouter(prefix="/occurrences", tags=["Ocorrencias"])


@router.post("", status_code=201)
async def create_occurrence(
    request: OccurrenceCreateRequest,
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
    audit_publisher=Depends(get_audit_publisher),
):
    require_role(current_user, {"admin", "comandante"})
    await require_base_access(current_user, request.base_id, domain_repository)
    occurrence = await domain_repository.create_occurrence(
        request.model_dump(),
        current_user["username"],
    )
    await audit_publisher.publish(
        "occurrence_created",
        {
            "occurrence_id": occurrence["id"],
            "base_id": occurrence["base_id"],
            "created_by": current_user["username"],
        },
    )
    return occurrence


@router.get("")
async def list_occurrences(
    status: str | None = None,
    base_id: str | None = None,
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
):
    if current_user["role"] != ROLE_ADMIN:
        allowed = await visible_base_ids(current_user, domain_repository)
        occurrences = await domain_repository.list_occurrences(status, None)
        return [item for item in occurrences if item.get("base_id") in (allowed or set())]
    return await domain_repository.list_occurrences(status, base_id)
