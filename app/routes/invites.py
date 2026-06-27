from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.dependencies import get_audit_publisher, get_current_user, get_invite_repository, require_role
from app.repositories.invites import InvalidInviteError
from app.domain.schemas import InviteCreateRequest

router = APIRouter(prefix="/invites", tags=["Convites"])


@router.get("")
async def list_invites(
    current_user: dict = Depends(get_current_user),
    invite_repository=Depends(get_invite_repository),
):
    require_role(current_user, {"admin"})
    return await invite_repository.list_invites()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_invite(
    request: InviteCreateRequest,
    current_user: dict = Depends(get_current_user),
    invite_repository=Depends(get_invite_repository),
    audit_publisher=Depends(get_audit_publisher),
):
    require_role(current_user, {"admin"})
    try:
        invite = await invite_repository.create_invite(
            request.model_dump(),
            current_user["username"],
        )
    except InvalidInviteError as error:
        raise HTTPException(status_code=400, detail="Convite invalido para o perfil") from error
    await audit_publisher.publish(
        "invite_created",
        {
            "invite_id": invite["id"],
            "base_id": invite["base_id"],
            "uf_scope": invite.get("uf_scope"),
            "role": invite["role"],
            "created_by": current_user["username"],
        },
    )
    return invite


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: str,
    current_user: dict = Depends(get_current_user),
    invite_repository=Depends(get_invite_repository),
    audit_publisher=Depends(get_audit_publisher),
):
    require_role(current_user, {"admin"})
    revoked = await invite_repository.revoke_invite(invite_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Convite nao encontrado")
    await audit_publisher.publish(
        "invite_revoked",
        {"invite_id": invite_id, "revoked_by": current_user["username"]},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
