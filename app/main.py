import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

from app.message_service import MessageService
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
from app.udp import UdpMessageProtocol
from app.websocket_manager import WebSocketConnectionManager, log_event


def create_app(
    udp_host: str | None = None,
    udp_port: int | None = None,
    message_repository: MessageRepository | None = None,
    presence_service: PresenceService | None = None,
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
    connections = WebSocketConnectionManager()
    pubsub_service = (
        RedisPubSubService(redis_url, connections)
        if redis_url
        else InMemoryPubSubService(connections)
    )
    message_service = MessageService(message_repository, pubsub_service)
    pending_disconnect_tasks: dict[tuple[str, str], asyncio.Task] = {}
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

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_schema = getattr(message_repository, "init_schema", None)
        if init_schema is not None:
            await init_schema()

        ping = getattr(presence_service, "ping", None)
        if ping is not None:
            await ping()
        
        await pubsub_service.start_listening()

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
            for task in pending_disconnect_tasks.values():
                task.cancel()
            transport.close()
            close_repository = getattr(message_repository, "close", None)
            if close_repository is not None:
                await close_repository()
            await pubsub_service.stop_listening()
            await presence_service.close()

    app = FastAPI(title="RescueRadio API", lifespan=lifespan)
    app.state.message_repository = message_repository
    app.state.presence_service = presence_service
    app.state.connections = connections
    app.state.message_service = message_service

    async def cancel_pending_disconnect(channel_id: str, usuario: str):
        task_key = (channel_id, usuario)
        pending_task = pending_disconnect_tasks.pop(task_key, None)

        if pending_task is None:
            return

        pending_task.cancel()
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
        except asyncio.CancelledError:
            raise
        finally:
            pending_disconnect_tasks.pop((channel_id, usuario), None)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "rescueradio-api",
            "transports": ["http", "websocket", "udp"],
        }

    @app.websocket("/ws/channel/{channel_id}")
    async def websocket_endpoint(
        websocket: WebSocket,
        channel_id: str,
        usuario: str = Query(...),
    ):
        usuario = usuario.strip()

        if not 1 <= len(usuario) <= 80:
            log_event(
                "websocket_rejected",
                channel_id=channel_id,
                reason="invalid_usuario",
            )
            await websocket.close(
                code=1008,
                reason="usuario deve ter entre 1 e 80 caracteres",
            )
            return

        await cancel_pending_disconnect(channel_id, usuario)
        await connections.connect(channel_id, usuario, websocket)
        await presence_service.connect(channel_id, usuario)

        await websocket.send_json({
            "type": "CONNECTED",
            "channel_id": channel_id,
            "usuario": usuario,
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
                    await websocket.send_json({
                        "type": "ERROR",
                        "channel_id": channel_id,
                        "message": "Payload deve conter JSON válido",
                    })
                    continue

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
                    await websocket.send_json({
                        "type": "ERROR",
                        "channel_id": channel_id,
                        "message": result,
                    })
        except WebSocketDisconnect:
            disconnected = connections.disconnect(
                channel_id,
                usuario,
                websocket,
            )

            if disconnected:
                pending_disconnect_tasks[(channel_id, usuario)] = asyncio.create_task(
                    finalize_disconnect(channel_id, usuario)
                )

    return app


app = create_app()
