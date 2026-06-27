import jwt
from fastapi import Depends, Header, HTTPException, Request, WebSocket, status

from app.domain.auth import ROLE_ADMIN, ROLE_COMANDANTE, decode_access_token
from app.infra.observability.metrics import AUTH_EVENTS, WEBSOCKET_ERRORS


def get_user_repository(request: Request):
    return request.app.state.user_repository


def get_domain_repository(request: Request):
    return request.app.state.domain_repository


def get_message_repository(request: Request):
    return request.app.state.message_repository


def get_invite_repository(request: Request):
    return request.app.state.invite_repository


def get_audit_publisher(request: Request):
    return request.app.state.audit_publisher


def get_pubsub_service(request: Request):
    return request.app.state.pubsub_service


def get_presence_service(request: Request):
    return request.app.state.presence_service


def get_connections(request: Request):
    return request.app.state.connections


def get_message_service(request: Request):
    return request.app.state.message_service


def get_notification_manager(request: Request):
    return request.app.state.notification_manager


def get_disconnect_manager(request: Request):
    return request.app.state.disconnect_manager


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    user_repository = request.app.state.user_repository

    if not authorization or not authorization.lower().startswith("bearer "):
        AUTH_EVENTS.labels(result="missing_token").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de acesso ausente",
        )

    token = authorization.split(" ", 1)[1].strip()

    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError as error:
        AUTH_EVENTS.labels(result="invalid_token").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de acesso invalido",
        ) from error

    user = await user_repository.get_by_username(str(payload.get("sub", "")))

    if user is None:
        AUTH_EVENTS.labels(result="unknown_user").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario nao encontrado",
        )

    return user


async def authenticate_websocket(websocket: WebSocket, token: str | None) -> dict | None:
    user_repository = websocket.app.state.user_repository

    if not token:
        WEBSOCKET_ERRORS.labels(reason="missing_token").inc()
        await websocket.close(code=1008, reason="token de acesso ausente")
        return None

    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        WEBSOCKET_ERRORS.labels(reason="invalid_token").inc()
        await websocket.close(code=1008, reason="token de acesso invalido")
        return None

    user = await user_repository.get_by_username(str(payload.get("sub", "")))

    if user is None:
        WEBSOCKET_ERRORS.labels(reason="unknown_user").inc()
        await websocket.close(code=1008, reason="usuario nao encontrado")
        return None

    return user


def require_role(user: dict, allowed_roles: set[str]):
    if user["role"] not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Perfil sem permissao para esta acao",
        )


async def require_base_access(user: dict, base_id: str, domain_repository) -> None:
    if user["role"] == ROLE_ADMIN:
        return
    bases = await domain_repository.list_bases()
    base = next((b for b in bases if b["id"] == base_id), None)
    if base is None:
        raise HTTPException(status_code=404, detail="Base nao encontrada")
    if user["role"] == ROLE_COMANDANTE:
        if (user.get("uf_scope") or "").upper() == (base.get("uf") or "").upper():
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a UF do comandante",
        )
    user_base_id = user.get("base_id")
    if not user_base_id:
        profile = await domain_repository.get_profile(user["username"])
        user_base_id = profile.get("base_id") if profile else None
    if user_base_id != base_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a propria base",
        )


async def visible_base_ids(user: dict, domain_repository) -> set[str] | None:
    if user["role"] == ROLE_ADMIN:
        return None
    bases = await domain_repository.list_bases()
    if user["role"] == ROLE_COMANDANTE:
        uf_scope = (user.get("uf_scope") or "").upper()
        return {base["id"] for base in bases if (base.get("uf") or "").upper() == uf_scope}
    user_base_id = user.get("base_id")
    if not user_base_id:
        profile = await domain_repository.get_profile(user["username"])
        user_base_id = profile.get("base_id") if profile else None
    return {user_base_id} if user_base_id else set()


async def users_from_usernames(usernames: list[str], user_repository) -> list[dict]:
    users = []
    for username in usernames:
        user = await user_repository.get_by_username(username)
        if user is not None:
            users.append(user)
    return users


async def require_members_in_user_base(
    current_user: dict,
    member_users: list[dict],
    domain_repository,
) -> None:
    if current_user["role"] == ROLE_ADMIN:
        return
    allowed = await visible_base_ids(current_user, domain_repository)
    for member in member_users:
        if member.get("base_id") not in (allowed or set()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operador fora do escopo operacional",
            )


def profile_is_complete(profile: dict | None) -> bool:
    return bool(
        profile
        and profile.get("full_name")
        and len(str(profile.get("full_name", "")).strip()) >= 6
        and profile.get("base_id")
    )
