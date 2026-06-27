import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import jwt
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware

from app.audit import AuditPublisher, create_audit_publisher
from app.auth import (
    ROLE_ADMIN,
    ROLE_COMANDANTE,
    ROLE_OPERADOR,
    create_access_token,
    decode_access_token,
    public_user,
    verify_password,
)
from app.invites import (
    InMemoryInviteRepository,
    InvalidInviteError,
    InviteRepository,
    PostgresInviteRepository,
)
from app.message_service import MessageService
from app.metrics import AUTH_EVENTS, RECONNECTIONS, WEBSOCKET_ERRORS, render_metrics
from app.notifications import NotificationManager
from app.operations import (
    DomainRepository,
    InMemoryDomainRepository,
    PostgresDomainRepository,
)
from app.presence import (
    InMemoryPresenceService,
    PresenceService,
    RedisPresenceService,
)
from app.pubsub import (
    InMemoryPubSubService,
    PubSubService,
    RedisPubSubService,
)
from app.state import (
    InMemoryMessageRepository,
    MessageRepository,
    PostgresMessageRepository,
)
from app.schemas import (
    BaseCreateRequest,
    BaseUpdateRequest,
    BootstrapAdminRequest,
    InviteCreateRequest,
    LoginRequest,
    OccurrenceCreateRequest,
    OperationCloseRequest,
    OperationCreateRequest,
    OperationMembersRequest,
    ProfileRequest,
    RegisterRequest,
    UserRoleUpdateRequest,
)
from app.udp import UdpMessageProtocol
from app.users import (
    DuplicateUserError,
    InMemoryUserRepository,
    PostgresUserRepository,
    UserRepository,
)
from app.websocket_manager import WebSocketConnectionManager, log_event


def create_app(
    udp_host: str | None = None,
    udp_port: int | None = None,
    message_repository: MessageRepository | None = None,
    presence_service: PresenceService | None = None,
    user_repository: UserRepository | None = None,
    domain_repository: DomainRepository | None = None,
    audit_publisher: AuditPublisher | None = None,
    invite_repository: InviteRepository | None = None,
    disconnect_grace_seconds: float | None = None,
) -> FastAPI:
    database_url = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL")
    message_repository = (
        message_repository
        or (
            PostgresMessageRepository(database_url)
            if database_url
            else InMemoryMessageRepository()
        )
    )
    presence_service = (
        presence_service
        or (
            RedisPresenceService(redis_url)
            if redis_url
            else InMemoryPresenceService()
        )
    )
    user_repository = (
        user_repository
        or (
            PostgresUserRepository(database_url)
            if database_url
            else InMemoryUserRepository()
        )
    )
    domain_repository = (
        domain_repository
        or (
            PostgresDomainRepository(database_url)
            if database_url
            else InMemoryDomainRepository()
        )
    )
    invite_repository = (
        invite_repository
        or (
            PostgresInviteRepository(database_url)
            if database_url
            else InMemoryInviteRepository()
        )
    )
    connections = WebSocketConnectionManager()
    notification_manager = NotificationManager()
    audit_publisher = audit_publisher or create_audit_publisher()
    pubsub_service = (
        RedisPubSubService(redis_url, connections)
        if redis_url
        else InMemoryPubSubService(connections)
    )
    async def channel_accepts_messages(channel_id: str) -> bool:
        operation = await domain_repository.get_operation_by_channel(channel_id)
        return operation is None or operation["status"] != "closed"

    message_service = MessageService(
        message_repository,
        pubsub_service,
        audit_publisher,
        channel_accepts_messages,
    )
    pending_disconnect_tasks: dict[tuple[str, str], asyncio.Task] = {}
    pending_disconnect_lock = asyncio.Lock()
    disconnect_grace_seconds = (
        disconnect_grace_seconds
        if disconnect_grace_seconds is not None
        else float(os.getenv("DISCONNECT_GRACE_SECONDS", "2"))
    )
    configured_host = udp_host or os.getenv("UDP_HOST", "0.0.0.0")
    configured_port = (
        udp_port
        if udp_port is not None
        else int(os.getenv("UDP_PORT", "9000"))
    )
    udp_enabled = (
        os.getenv("ENABLE_UDP", "false").lower() in {"1", "true", "yes"}
        or udp_host is not None
        or udp_port is not None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_schema = getattr(message_repository, "init_schema", None)
        if init_schema is not None:
            await init_schema()
        await user_repository.init_schema()
        await domain_repository.init_schema()
        await invite_repository.init_schema()

        ping = getattr(presence_service, "ping", None)
        if ping is not None:
            await ping()
        
        await pubsub_service.start_listening()
        await audit_publisher.start()

        transport = None
        if udp_enabled:
            loop = asyncio.get_running_loop()
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: UdpMessageProtocol(message_service),
                local_addr=(configured_host, configured_port),
            )
            app.state.udp_transport = transport
            app.state.udp_protocol = protocol
            app.state.udp_port = transport.get_extra_info("sockname")[1]

        try:
            yield
        finally:
            async with pending_disconnect_lock:
                for task in pending_disconnect_tasks.values():
                    task.cancel()
            if transport is not None:
                transport.close()
            close_repository = getattr(message_repository, "close", None)
            if close_repository is not None:
                await close_repository()
            await user_repository.close()
            await domain_repository.close()
            await invite_repository.close()
            await audit_publisher.stop()
            await pubsub_service.stop_listening()
            await presence_service.close()

    openapi_tags = [
        {"name": "Observabilidade", "description": "Saude da API e metricas Prometheus."},
        {"name": "Autenticacao", "description": "Bootstrap, login, cadastro por convite e sessao."},
        {"name": "Convites", "description": "Convites de cadastro gerenciados por admin."},
        {"name": "Bases", "description": "Bases operacionais e cidades de cobertura."},
        {"name": "Usuarios", "description": "Gestao administrativa de usuarios e roles."},
        {"name": "Perfis", "description": "Perfil operacional do usuario autenticado."},
        {"name": "Operadores", "description": "Consulta de operadores por base, status e competencia."},
        {"name": "Ocorrencias", "description": "Registro e consulta de ocorrencias."},
        {"name": "Operacoes", "description": "Criacao, participantes, encerramento e auditoria de operacoes."},
        {"name": "Chat", "description": "Acoes administrativas sobre canais de chat."},
    ]

    app = FastAPI(title="RescueRadio API", lifespan=lifespan, openapi_tags=openapi_tags)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip()
            for origin in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
            if origin.strip()
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.message_repository = message_repository
    app.state.presence_service = presence_service
    app.state.user_repository = user_repository
    app.state.domain_repository = domain_repository
    app.state.invite_repository = invite_repository
    app.state.connections = connections
    app.state.message_service = message_service
    app.state.notification_manager = notification_manager

    async def cancel_pending_disconnect(channel_id: str, usuario: str):
        task_key = (channel_id, usuario)
        async with pending_disconnect_lock:
            pending_task = pending_disconnect_tasks.pop(task_key, None)

        if pending_task is None:
            return

        pending_task.cancel()
        RECONNECTIONS.labels(channel_id=channel_id).inc()
        log_event(
            "websocket_disconnect_cancelled",
            channel_id=channel_id,
            usuario=usuario,
        )

    async def finalize_disconnect(channel_id: str, usuario: str):
        try:
            if disconnect_grace_seconds > 0:
                await asyncio.sleep(disconnect_grace_seconds)

            await presence_service.disconnect(channel_id, usuario)
            await pubsub_service.publish_message(channel_id, {
                "type": "MEMBER_LEFT",
                "channel_id": channel_id,
                "usuario": usuario,
                "timestamp_iso": datetime.now(timezone.utc).isoformat(),
                "members": await presence_service.get_active_members(channel_id),
                "message": f"{usuario} saiu do canal.",
            })
            await audit_publisher.publish(
                "member_left",
                {"channel_id": channel_id, "usuario": usuario},
            )
        except asyncio.CancelledError:
            raise
        finally:
            async with pending_disconnect_lock:
                pending_disconnect_tasks.pop((channel_id, usuario), None)

    async def get_current_user(authorization: str | None = Header(default=None)):
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

    async def authenticate_websocket(
        websocket: WebSocket,
        token: str | None,
    ) -> dict | None:
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

    async def require_base_access(user: dict, base_id: str):
        if user["role"] == ROLE_ADMIN:
            return
        bases = await domain_repository.list_bases()
        base = next((item for item in bases if item["id"] == base_id), None)
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

    def profile_is_complete(profile: dict | None) -> bool:
        return bool(
            profile
            and profile.get("full_name")
            and len(str(profile.get("full_name", "")).strip()) >= 6
            and profile.get("base_id")
        )

    async def visible_base_ids(user: dict) -> set[str] | None:
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

    async def users_from_usernames(usernames: list[str]) -> list[dict]:
        users = []
        for username in usernames:
            user = await user_repository.get_by_username(username)
            if user is not None:
                users.append(user)
        return users

    async def require_members_in_user_base(current_user: dict, member_users: list[dict]):
        if current_user["role"] == ROLE_ADMIN:
            return
        allowed_bases = await visible_base_ids(current_user)
        for member in member_users:
            if member.get("base_id") not in (allowed_bases or set()):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Operador fora do escopo operacional",
                )

    async def notify_operation_assigned(operation: dict, member_users: list[dict], assigned_by: str):
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

    @app.get("/health", tags=["Observabilidade"])
    def health():
        return {
            "status": "ok",
            "service": "rescueradio-api",
            "transports": ["http", "websocket"] + (["udp"] if udp_enabled else []),
        }

    @app.get("/metrics", tags=["Observabilidade"])
    def metrics():
        payload, content_type = render_metrics()
        return Response(content=payload, media_type=content_type)

    @app.post("/auth/register", status_code=status.HTTP_201_CREATED, tags=["Autenticacao"])
    async def register(request: RegisterRequest):
        if await user_repository.get_by_username(request.username) is not None:
            AUTH_EVENTS.labels(result="duplicate_register").inc()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Usuario ja cadastrado",
            )
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
            {
                "username": user["username"],
                "role": user["role"],
                "base_id": user.get("base_id"),
            },
        )
        return public_user(user)

    @app.post(
        "/auth/bootstrap-admin",
        status_code=status.HTTP_201_CREATED,
        tags=["Autenticacao"],
    )
    async def bootstrap_admin(request: BootstrapAdminRequest):
        expected_key = os.getenv("BOOTSTRAP_ADMIN_KEY", "rescueradio-bootstrap")
        if request.bootstrap_key != expected_key:
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

    @app.post("/auth/login", tags=["Autenticacao"])
    async def login(request: LoginRequest):
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
            {
                "username": user["username"],
                "role": user["role"],
            },
        )
        return {
            "access_token": create_access_token(user),
            "token_type": "bearer",
            "user": public_user(user),
        }

    @app.get("/auth/me", tags=["Autenticacao"])
    async def me(current_user: dict = Depends(get_current_user)):
        return public_user(current_user)

    @app.get("/bases", tags=["Bases"])
    async def list_bases(current_user: dict = Depends(get_current_user)):
        bases = await domain_repository.list_bases()
        allowed = await visible_base_ids(current_user)
        if allowed is None:
            return bases
        return [base for base in bases if base["id"] in allowed]

    @app.post("/bases", status_code=status.HTTP_201_CREATED, tags=["Bases"])
    async def create_base(
        request: BaseCreateRequest,
        current_user: dict = Depends(get_current_user),
    ):
        require_role(current_user, {"admin", "comandante"})
        if current_user["role"] == ROLE_COMANDANTE:
            data = request.model_dump()
            data["uf"] = current_user.get("uf_scope")
            return await domain_repository.create_base(data)
        return await domain_repository.create_base(request.model_dump())

    @app.patch("/bases/{base_id}", tags=["Bases"])
    async def update_base(
        base_id: str,
        request: BaseUpdateRequest,
        current_user: dict = Depends(get_current_user),
    ):
        require_role(current_user, {"admin", "comandante"})
        if current_user["role"] == ROLE_COMANDANTE:
            await require_base_access(current_user, base_id)
            data = request.model_dump()
            data["uf"] = current_user.get("uf_scope")
            base = await domain_repository.update_base(base_id, data)
            if base is None:
                raise HTTPException(status_code=404, detail="Base nao encontrada")
            return base
        base = await domain_repository.update_base(base_id, request.model_dump())
        if base is None:
            raise HTTPException(status_code=404, detail="Base nao encontrada")
        return base

    @app.delete("/bases/{base_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Bases"])
    async def delete_base(
        base_id: str,
        current_user: dict = Depends(get_current_user),
    ):
        require_role(current_user, {"admin", "comandante"})
        if current_user["role"] == ROLE_COMANDANTE:
            await require_base_access(current_user, base_id)
        deleted = await domain_repository.delete_base(base_id)
        if not deleted:
            raise HTTPException(status_code=400, detail="Base nao pode ser excluida")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/invites", tags=["Convites"])
    async def list_invites(current_user: dict = Depends(get_current_user)):
        require_role(current_user, {"admin"})
        return await invite_repository.list_invites()

    @app.post("/invites", status_code=status.HTTP_201_CREATED, tags=["Convites"])
    async def create_invite(
        request: InviteCreateRequest,
        current_user: dict = Depends(get_current_user),
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

    @app.delete(
        "/invites/{invite_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["Convites"],
    )
    async def revoke_invite(
        invite_id: str,
        current_user: dict = Depends(get_current_user),
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

    @app.delete("/channels/{channel_id}/messages", tags=["Chat"])
    async def clear_channel_messages(
        channel_id: str,
        current_user: dict = Depends(get_current_user),
    ):
        require_role(current_user, {"admin"})
        removed = await message_repository.clear_channel(channel_id)
        await pubsub_service.publish_message(
            channel_id,
            {
                "type": "CHAT_CLEARED",
                "channel_id": channel_id,
                "cleared_by": current_user["username"],
                "removed": removed,
            },
        )
        await audit_publisher.publish(
            "chat_cleared",
            {
                "channel_id": channel_id,
                "removed": removed,
                "cleared_by": current_user["username"],
            },
        )
        return {"channel_id": channel_id, "removed": removed}

    @app.get("/users", tags=["Usuarios"])
    async def list_users(current_user: dict = Depends(get_current_user)):
        require_role(current_user, {"admin"})
        users = await user_repository.list_users()
        profiles = {
            profile["username"]: profile
            for profile in await domain_repository.list_operator_profiles()
        }
        return [
            {
                **public_user(user),
                "profile": profiles.get(user["username"]),
            }
            for user in users
        ]

    @app.patch("/users/{username}/role", tags=["Usuarios"])
    async def update_user_role(
        username: str,
        request: UserRoleUpdateRequest,
        current_user: dict = Depends(get_current_user),
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

    @app.delete("/users/{username}", status_code=status.HTTP_204_NO_CONTENT, tags=["Usuarios"])
    async def delete_user(
        username: str,
        current_user: dict = Depends(get_current_user),
    ):
        require_role(current_user, {"admin"})
        normalized_username = username.strip()
        if normalized_username == current_user["username"]:
            raise HTTPException(status_code=400, detail="Usuario autenticado nao pode se excluir")
        existing_user = await user_repository.get_by_username(normalized_username)
        if existing_user is None:
            raise HTTPException(status_code=404, detail="Usuario nao encontrado")
        await domain_repository.delete_profile(normalized_username)
        deleted = await user_repository.delete_user(normalized_username)
        if not deleted:
            raise HTTPException(status_code=404, detail="Usuario nao encontrado")
        await audit_publisher.publish(
            "user_deleted",
            {
                "username": normalized_username,
                "deleted_by": current_user["username"],
            },
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/profiles/me", tags=["Perfis"])
    async def get_my_profile(current_user: dict = Depends(get_current_user)):
        profile = await domain_repository.get_profile(current_user["username"])
        return {
            "user": public_user(current_user),
            "profile": profile,
            "complete": profile_is_complete(profile),
        }

    @app.put("/profiles/me", tags=["Perfis"])
    async def upsert_my_profile(
        request: ProfileRequest,
        current_user: dict = Depends(get_current_user),
    ):
        data = request.model_dump()
        locked_base_id = current_user.get("base_id")
        if current_user["role"] != ROLE_ADMIN and locked_base_id:
            data["base_id"] = locked_base_id
        if current_user["role"] != ROLE_ADMIN:
            await require_base_access(current_user, data["base_id"])
        profile = await domain_repository.upsert_profile(
            current_user["username"],
            data,
        )
        display_name = data.get("display_name") or profile.get("display_name") or profile["operational_name"]
        await user_repository.update_identity(
            current_user["username"],
            display_name=display_name,
            base_id=profile.get("base_id"),
        )
        await audit_publisher.publish(
            "operator_profile_updated",
            {
                "username": current_user["username"],
                "base_id": profile["base_id"],
            },
        )
        return profile

    @app.get("/operators", tags=["Operadores"])
    async def list_operators(
        base_id: str | None = None,
        status: str | None = None,
        skill: str | None = None,
        current_user: dict = Depends(get_current_user),
    ):
        if current_user["role"] != ROLE_ADMIN:
            allowed = await visible_base_ids(current_user)
            operators = await domain_repository.list_operator_profiles(None, status, skill)
            return [operator for operator in operators if operator.get("base_id") in (allowed or set())]
        return await domain_repository.list_operator_profiles(base_id, status, skill)

    @app.post("/occurrences", status_code=status.HTTP_201_CREATED, tags=["Ocorrencias"])
    async def create_occurrence(
        request: OccurrenceCreateRequest,
        current_user: dict = Depends(get_current_user),
    ):
        require_role(current_user, {"admin", "comandante"})
        await require_base_access(current_user, request.base_id)
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

    @app.get("/occurrences", tags=["Ocorrencias"])
    async def list_occurrences(
        status: str | None = None,
        base_id: str | None = None,
        current_user: dict = Depends(get_current_user),
    ):
        if current_user["role"] != ROLE_ADMIN:
            allowed = await visible_base_ids(current_user)
            occurrences = await domain_repository.list_occurrences(status, None)
            return [item for item in occurrences if item.get("base_id") in (allowed or set())]
        return await domain_repository.list_occurrences(status, base_id)

    @app.post("/operations", status_code=status.HTTP_201_CREATED, tags=["Operacoes"])
    async def create_operation(
        request: OperationCreateRequest,
        current_user: dict = Depends(get_current_user),
    ):
        require_role(current_user, {"admin", "comandante"})
        await require_base_access(current_user, request.occurrence.base_id)
        occurrence = await domain_repository.create_occurrence(
            request.occurrence.model_dump(),
            current_user["username"],
        )
        member_users = await users_from_usernames(request.member_usernames)
        await require_members_in_user_base(current_user, member_users)
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
                "members": [user["username"] for user in member_users],
                "created_by": current_user["username"],
            },
        )
        await notify_operation_assigned(operation, member_users, current_user["username"])
        return operation

    @app.get("/operations", tags=["Operacoes"])
    async def list_operations(
        status: str | None = None,
        base_id: str | None = None,
        current_user: dict = Depends(get_current_user),
    ):
        if current_user["role"] != ROLE_ADMIN:
            allowed = await visible_base_ids(current_user)
            operations = await domain_repository.list_operations(status, None)
            return [item for item in operations if item.get("base_id") in (allowed or set())]
        return await domain_repository.list_operations(status, base_id)

    @app.get("/operations/{operation_id}", tags=["Operacoes"])
    async def get_operation(
        operation_id: str,
        current_user: dict = Depends(get_current_user),
    ):
        operation = await domain_repository.get_operation(operation_id)
        if operation is None:
            raise HTTPException(status_code=404, detail="Operacao nao encontrada")
        await require_base_access(current_user, operation["base_id"])
        return operation

    @app.post("/operations/{operation_id}/members", tags=["Operacoes"])
    async def add_operation_members(
        operation_id: str,
        request: OperationMembersRequest,
        current_user: dict = Depends(get_current_user),
    ):
        require_role(current_user, {"admin", "comandante"})
        operation = await domain_repository.get_operation(operation_id)
        if operation is None:
            raise HTTPException(status_code=404, detail="Operacao nao encontrada")
        await require_base_access(current_user, operation["base_id"])
        member_users = await users_from_usernames(request.usernames)
        await require_members_in_user_base(current_user, member_users)
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
                "members": [user["username"] for user in member_users],
                "assigned_by": current_user["username"],
            },
        )
        operation = await domain_repository.get_operation(operation_id)
        if operation is not None:
            await notify_operation_assigned(operation, member_users, current_user["username"])
        return members

    @app.post("/operations/{operation_id}/close", tags=["Operacoes"])
    async def close_operation(
        operation_id: str,
        request: OperationCloseRequest,
        current_user: dict = Depends(get_current_user),
    ):
        require_role(current_user, {"admin", "comandante"})
        existing_operation = await domain_repository.get_operation(operation_id)
        if existing_operation is None:
            raise HTTPException(status_code=404, detail="Operacao nao encontrada")
        await require_base_access(current_user, existing_operation["base_id"])
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
            {
                "operation_id": operation_id,
                "closed_by": current_user["username"],
            },
        )
        return operation

    @app.get("/operations/{operation_id}/audit", tags=["Operacoes"])
    async def get_operation_audit(
        operation_id: str,
        current_user: dict = Depends(get_current_user),
    ):
        operation = await domain_repository.get_operation(operation_id)
        if operation is None:
            raise HTTPException(status_code=404, detail="Operacao nao encontrada")
        await require_base_access(current_user, operation["base_id"])
        messages = await message_repository.get_channel_messages(operation["channel_id"])
        audit = await domain_repository.get_operation_audit(operation_id, messages)
        return audit

    @app.websocket("/ws/notifications")
    async def notifications_endpoint(
        websocket: WebSocket,
        token: str | None = Query(default=None),
    ):
        user = await authenticate_websocket(websocket, token)
        if user is None:
            return

        username = user["username"]
        await notification_manager.connect(username, websocket)
        await websocket.send_json({
            "type": "NOTIFICATIONS_CONNECTED",
            "username": username,
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
        })

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            await notification_manager.disconnect(username, websocket)

    @app.websocket("/ws/channel/{channel_id}")
    async def websocket_endpoint(
        websocket: WebSocket,
        channel_id: str,
        token: str | None = Query(default=None),
    ):
        user = await authenticate_websocket(websocket, token)

        if user is None:
            return

        usuario = user["display_name"]
        username = user["username"]

        await cancel_pending_disconnect(channel_id, usuario)
        await connections.connect(channel_id, usuario, websocket)
        await presence_service.connect(channel_id, usuario)
        await domain_repository.update_presence(username, "online")

        await websocket.send_json({
            "type": "CONNECTED",
            "channel_id": channel_id,
            "usuario": usuario,
            "username": username,
            "role": user["role"],
            "message": "Conectado ao canal com sucesso.",
        })
        await websocket.send_json({
            "type": "BRIEFING",
            "channel_id": channel_id,
            "messages": await message_repository.get_briefing(channel_id),
        })
        await pubsub_service.publish_message(channel_id, {
            "type": "MEMBER_JOINED",
            "channel_id": channel_id,
            "usuario": usuario,
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "members": await presence_service.get_active_members(channel_id),
            "message": f"{usuario} entrou no canal.",
        })
        await audit_publisher.publish(
            "member_joined",
            {
                "channel_id": channel_id,
                "usuario": usuario,
                "role": user["role"],
            },
        )

        try:
            while True:
                try:
                    data = await websocket.receive_json()
                except json.JSONDecodeError:
                    log_event(
                        "websocket_malformed_json",
                        channel_id=channel_id,
                        usuario=usuario,
                    )
                    WEBSOCKET_ERRORS.labels(reason="malformed_json").inc()
                    await websocket.send_json({
                        "type": "ERROR",
                        "channel_id": channel_id,
                        "message": "Payload deve conter JSON válido",
                    })
                    continue

                if isinstance(data, dict):
                    data = {**data, "usuario": usuario}

                is_valid, result = await message_service.publish(
                    channel_id,
                    data,
                    exclude_usuario=usuario,
                )

                if not is_valid:
                    log_event(
                        "websocket_invalid_payload",
                        channel_id=channel_id,
                        usuario=usuario,
                        reason=str(result),
                    )
                    WEBSOCKET_ERRORS.labels(reason="invalid_payload").inc()
                    await websocket.send_json({
                        "type": "ERROR",
                        "channel_id": channel_id,
                        "message": result,
                    })
        except WebSocketDisconnect:
            await domain_repository.update_presence(
                username,
                "offline",
                datetime.now(timezone.utc).isoformat(),
            )
            disconnected = await connections.disconnect(
                channel_id,
                usuario,
                websocket,
            )

            if disconnected:
                async with pending_disconnect_lock:
                    pending_disconnect_tasks[(channel_id, usuario)] = (
                        asyncio.create_task(finalize_disconnect(channel_id, usuario))
                    )

    return app


app = create_app()
