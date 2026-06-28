from fastapi import APIRouter, Depends

from app.domain.auth import ROLE_ADMIN
from app.dependencies import get_current_user, get_domain_repository, visible_base_ids

router = APIRouter(prefix="/operators", tags=["Operadores"])


@router.get("")
async def list_operators(
    base_id: str | None = None,
    status: str | None = None,
    skill: str | None = None,
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
):
    if current_user["role"] != ROLE_ADMIN:
        allowed = await visible_base_ids(current_user, domain_repository)
        operators = await domain_repository.list_operator_profiles(None, status, skill)
        return [op for op in operators if op.get("base_id") in (allowed or set())]
    return await domain_repository.list_operator_profiles(base_id, status, skill)
