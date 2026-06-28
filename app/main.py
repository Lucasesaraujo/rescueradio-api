import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.infra.db.engine import make_engine
from app.infra.messaging.audit import create_audit_publisher
from app.infra.messaging.notifications import NotificationManager
from app.infra.messaging.pubsub import InMemoryPubSubService, RedisPubSubService
from app.infra.cache.presence import InMemoryPresenceService, RedisPresenceService
from app.infra.transport.disconnect import DisconnectManager
from app.infra.transport.udp import UdpMessageProtocol
from app.infra.transport.websocket_manager import WebSocketConnectionManager
from app.operations import InMemoryDomainRepository, PostgresDomainRepository
from app.repositories.invites import InMemoryInviteRepository, PostgresInviteRepository
from app.repositories.messages import InMemoryMessageRepository, PostgresMessageRepository
from app.repositories.users import InMemoryUserRepository, PostgresUserRepository
from app.routes import auth, bases, channels, health, invites, occurrences, operators, operations, profiles, users, websockets
from app.services.message_service import MessageService


def create_app(
    message_repository=None,
    presence_service=None,
    user_repository=None,
    domain_repository=None,
    audit_publisher=None,
    invite_repository=None,
    disconnect_grace_seconds: float | None = None,
    udp_host: str | None = None,
    udp_port: int | None = None,
) -> FastAPI:
    settings = get_settings()

    redis_url = settings.redis_url
    engine = make_engine(settings.database_url) if settings.database_url else None

    message_repository = message_repository or (
        PostgresMessageRepository(engine) if engine else InMemoryMessageRepository()
    )
    user_repository = user_repository or (
        PostgresUserRepository(engine) if engine else InMemoryUserRepository()
    )
    domain_repository = domain_repository or (
        PostgresDomainRepository(engine) if engine else InMemoryDomainRepository()
    )
    invite_repository = invite_repository or (
        PostgresInviteRepository(engine) if engine else InMemoryInviteRepository()
    )
    presence_service = presence_service or (
        RedisPresenceService(redis_url) if redis_url else InMemoryPresenceService()
    )

    connections = WebSocketConnectionManager()
    notification_manager = NotificationManager()
    audit_publisher = audit_publisher or create_audit_publisher()

    pubsub_service = (
        RedisPubSubService(redis_url, connections) if redis_url else InMemoryPubSubService(connections)
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

    grace_seconds = (
        disconnect_grace_seconds
        if disconnect_grace_seconds is not None
        else settings.disconnect_grace_seconds
    )
    disconnect_manager = DisconnectManager(grace_seconds)

    udp_enabled = (
        settings.enable_udp
        or udp_host is not None
        or udp_port is not None
    )
    configured_host = udp_host or settings.udp_host
    configured_port = udp_port if udp_port is not None else settings.udp_port

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
            await disconnect_manager.cancel_all()
            if transport is not None:
                transport.close()
            close_repo = getattr(message_repository, "close", None)
            if close_repo is not None:
                await close_repo()
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
        allow_origins=[o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.message_repository = message_repository
    app.state.presence_service = presence_service
    app.state.user_repository = user_repository
    app.state.domain_repository = domain_repository
    app.state.invite_repository = invite_repository
    app.state.audit_publisher = audit_publisher
    app.state.pubsub_service = pubsub_service
    app.state.connections = connections
    app.state.message_service = message_service
    app.state.notification_manager = notification_manager
    app.state.disconnect_manager = disconnect_manager
    app.state.udp_enabled = udp_enabled

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(invites.router)
    app.include_router(bases.router)
    app.include_router(users.router)
    app.include_router(profiles.router)
    app.include_router(operators.router)
    app.include_router(occurrences.router)
    app.include_router(operations.router)
    app.include_router(channels.router)
    app.include_router(websockets.router)

    return app


app = create_app()
