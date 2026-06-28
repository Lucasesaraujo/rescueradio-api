from fastapi import APIRouter, Depends, HTTPException, status

from app.domain.auth import ROLE_ADMIN, create_access_token, public_user, verify_password
from app.config import get_settings
from app.dependencies import get_audit_publisher, get_current_user, get_invite_repository, get_user_repository
from app.infra.observability.metrics import AUTH_EVENTS
from app.repositories.invites import InvalidInviteError
from app.repositories.users import DuplicateUserError
from app.domain.schemas import BootstrapAdminRequest, LoginRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["Autenticacao"])


@router.post("/bootstrap-admin", status_code=status.HTTP_201_CREATED)
async def bootstrap_admin(
    request: BootstrapAdminRequest,
    user_repository=Depends(get_user_repository),
    audit_publisher=Depends(get_audit_publisher),
):
    if request.bootstrap_key != get_settings().bootstrap_admin_key:
        AUTH_EVENTS.labels(result="bootstrap_invalid_key").inc()
        raise HTTPException(status_code=403, detail="Chave de bootstrap invalida")
    if await user_repository.has_admin():
        AUTH_EVENTS.labels(result="bootstrap_blocked").inc()
        raise HTTPException(status_code=409, detail="Admin inicial ja existe")
    try:
        user = await user_repository.create_user(
            request.username,
            request.password,
            request.display_name,
            ROLE_ADMIN,
        )
    except DuplicateUserError as error:
        raise HTTPException(status_code=409, detail="Usuario ja cadastrado") from error
    AUTH_EVENTS.labels(result="bootstrap_admin").inc()
    await audit_publisher.publish(
        "bootstrap_admin_created",
        {"username": user["username"], "role": user["role"]},
    )
    return public_user(user)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    user_repository=Depends(get_user_repository),
    invite_repository=Depends(get_invite_repository),
    audit_publisher=Depends(get_audit_publisher),
):
    if await user_repository.get_by_username(request.username) is not None:
        AUTH_EVENTS.labels(result="duplicate_register").inc()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Usuario ja cadastrado")
    try:
        invite = await invite_repository.consume_invite(request.invite_code, request.username)
    except InvalidInviteError as error:
        AUTH_EVENTS.labels(result="invalid_invite").inc()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Convite invalido, expirado ou ja utilizado",
        ) from error
    try:
        user = await user_repository.create_user(
            request.username,
            request.password,
            request.display_name,
            invite["role"],
            invite["base_id"],
            invite.get("uf_scope"),
        )
    except DuplicateUserError as error:
        AUTH_EVENTS.labels(result="duplicate_register").inc()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Usuario ja cadastrado",
        ) from error
    AUTH_EVENTS.labels(result="registered").inc()
    await audit_publisher.publish(
        "user_registered",
        {"username": user["username"], "role": user["role"], "base_id": user.get("base_id")},
    )
    return public_user(user)


@router.post("/login")
async def login(
    request: LoginRequest,
    user_repository=Depends(get_user_repository),
    audit_publisher=Depends(get_audit_publisher),
):
    user = await user_repository.get_by_username(request.username)
    if user is None or not verify_password(request.password, user["password_hash"]):
        AUTH_EVENTS.labels(result="login_failed").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais invalidas",
        )
    AUTH_EVENTS.labels(result="login_success").inc()
    await audit_publisher.publish(
        "user_login",
        {"username": user["username"], "role": user["role"]},
    )
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "user": public_user(user),
    }


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    return public_user(current_user)
