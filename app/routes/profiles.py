from fastapi import APIRouter, Depends

from app.domain.auth import ROLE_ADMIN, public_user
from app.dependencies import (
    get_audit_publisher,
    get_current_user,
    get_domain_repository,
    get_user_repository,
    profile_is_complete,
    require_base_access,
)
from app.domain.schemas import ProfileRequest

router = APIRouter(prefix="/profiles", tags=["Perfis"])


@router.get("/me")
async def get_my_profile(
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
):
    profile = await domain_repository.get_profile(current_user["username"])
    return {
        "user": public_user(current_user),
        "profile": profile,
        "complete": profile_is_complete(profile),
    }


@router.put("/me")
async def upsert_my_profile(
    request: ProfileRequest,
    current_user: dict = Depends(get_current_user),
    domain_repository=Depends(get_domain_repository),
    user_repository=Depends(get_user_repository),
    audit_publisher=Depends(get_audit_publisher),
):
    data = request.model_dump()
    locked_base_id = current_user.get("base_id")
    if current_user["role"] != ROLE_ADMIN and locked_base_id:
        data["base_id"] = locked_base_id
    if current_user["role"] != ROLE_ADMIN:
        await require_base_access(current_user, data["base_id"], domain_repository)
    profile = await domain_repository.upsert_profile(current_user["username"], data)
    display_name = (
        data.get("display_name")
        or profile.get("display_name")
        or profile["operational_name"]
    )
    await user_repository.update_identity(
        current_user["username"],
        display_name=display_name,
        base_id=profile.get("base_id"),
    )
    await audit_publisher.publish(
        "operator_profile_updated",
        {"username": current_user["username"], "base_id": profile["base_id"]},
    )
    return profile
