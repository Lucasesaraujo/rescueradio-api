from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.domain.auth import ROLE_COMANDANTE, ROLE_OPERADOR, public_user
from app.dependencies import (
    get_audit_publisher,
    get_current_user,
    get_domain_repository,
    get_user_repository,
    require_role,
)
from app.domain.schemas import UserRoleUpdateRequest

router = APIRouter(prefix="/users", tags=["Usuarios"])


@router.get("")
async def list_users(
    current_user: dict = Depends(get_current_user),
    user_repository=Depends(get_user_repository),
    domain_repository=Depends(get_domain_repository),
):
    require_role(current_user, {"admin"})
    users = await user_repository.list_users()
    profiles = {
        profile["username"]: profile
        for profile in await domain_repository.list_operator_profiles()
    }
    return [
        {**public_user(user), "profile": profiles.get(user["username"])}
        for user in users
    ]


@router.patch("/{username}/role")
async def update_user_role(
    username: str,
    request: UserRoleUpdateRequest,
    current_user: dict = Depends(get_current_user),
    user_repository=Depends(get_user_repository),
    audit_publisher=Depends(get_audit_publisher),
):
    require_role(current_user, {"admin"})
    if request.role == ROLE_COMANDANTE and not request.uf_scope:
        raise HTTPException(status_code=400, detail="Comandante exige UF de escopo")
    if request.role == ROLE_OPERADOR and not request.base_id:
        raise HTTPException(status_code=400, detail="Operador exige base vinculada")
    user = await user_repository.update_role(
        username,
        request.role,
        request.base_id,
        request.uf_scope,
    )
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    await audit_publisher.publish(
        "user_role_updated",
        {
            "username": username,
            "role": request.role,
            "base_id": request.base_id,
            "uf_scope": request.uf_scope,
            "updated_by": current_user["username"],
        },
    )
    return public_user(user)


@router.delete("/{username}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    username: str,
    current_user: dict = Depends(get_current_user),
    user_repository=Depends(get_user_repository),
    domain_repository=Depends(get_domain_repository),
    audit_publisher=Depends(get_audit_publisher),
):
    require_role(current_user, {"admin"})
    normalized = username.strip()
    if normalized == current_user["username"]:
        raise HTTPException(status_code=400, detail="Usuario autenticado nao pode se excluir")
    if await user_repository.get_by_username(normalized) is None:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    await domain_repository.delete_profile(normalized)
    deleted = await user_repository.delete_user(normalized)
    if not deleted:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    await audit_publisher.publish(
        "user_deleted",
        {"username": normalized, "deleted_by": current_user["username"]},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
