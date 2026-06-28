from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.domain.auth import ROLE_COMANDANTE
from app.dependencies import (
    get_audit_publisher,
    get_current_user,
    get_domain_repository,
    require_base_access,
    require_role,
    visible_base_ids,
)
from app.domain.schemas import BaseCreateRequest, BaseUpdateRequest

router = APIRouter(prefix="/bases", tags=["Bases"])


@router.get("")
async def list_bases(
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
):
    bases = await domain_repository.list_bases()
    allowed = await visible_base_ids(current_user, domain_repository)
    if allowed is None:
        return bases
    return [base for base in bases if base["id"] in allowed]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_base(
    request: BaseCreateRequest,
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
):
    require_role(current_user, {"admin", "comandante"})
    data = request.model_dump()
    if current_user["role"] == ROLE_COMANDANTE:
        data["uf"] = current_user.get("uf_scope")
    return await domain_repository.create_base(data)


@router.patch("/{base_id}")
async def update_base(
    base_id: str,
    request: BaseUpdateRequest,
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
):
    require_role(current_user, {"admin", "comandante"})
    data = request.model_dump()
    if current_user["role"] == ROLE_COMANDANTE:
        await require_base_access(current_user, base_id, domain_repository)
        data["uf"] = current_user.get("uf_scope")
    base = await domain_repository.update_base(base_id, data)
    if base is None:
        raise HTTPException(status_code=404, detail="Base nao encontrada")
    return base


@router.delete("/{base_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_base(
    base_id: str,
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
):
    require_role(current_user, {"admin", "comandante"})
    if current_user["role"] == ROLE_COMANDANTE:
        await require_base_access(current_user, base_id, domain_repository)
    deleted = await domain_repository.delete_base(base_id)
    if not deleted:
        raise HTTPException(status_code=400, detail="Base nao pode ser excluida")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
