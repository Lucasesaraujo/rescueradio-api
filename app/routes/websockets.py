import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.dependencies import authenticate_websocket
from app.logging import log_event
from app.infra.observability.metrics import RECONNECTIONS, WEBSOCKET_ERRORS

router = APIRouter(tags=["WebSocket"])


async def _finalize_disconnect(
    channel_id: str,
    usuario: str,
    grace_seconds: float,
    presence_service,
    pubsub_service,
    audit_publisher,
):
    try:
        if grace_seconds > 0:
            await asyncio.sleep(grace_seconds)
        await presence_service.disconnect(channel_id, usuario)
        await pubsub_service.publish_message(
            channel_id,
            {
                "type": "MEMBER_LEFT",
                "channel_id": channel_id,
                "usuario": usuario,
                "timestamp_iso": datetime.now(timezone.utc).isoformat(),
                "members": await presence_service.get_active_members(channel_id),
                "message": f"{usuario} saiu do canal.",
            },
        )
        await audit_publisher.publish(
            "member_left",
            {"channel_id": channel_id, "usuario": usuario},
        )
    except asyncio.CancelledError:
        raise


@router.websocket("/ws/notifications")
async def notifications_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None),
):
    user = await authenticate_websocket(websocket, token)
    if user is None:
        return

    notification_manager = websocket.app.state.notification_manager
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


@router.websocket("/ws/channel/{channel_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    channel_id: str,
    token: str | None = Query(default=None),
):
    user = await authenticate_websocket(websocket, token)
    if user is None:
        return

    state = websocket.app.state
    connections = state.connections
    presence_service = state.presence_service
    pubsub_service = state.pubsub_service
    domain_repository = state.domain_repository
    message_repository = state.message_repository
    message_service = state.message_service
    audit_publisher = state.audit_publisher
    disconnect_manager = state.disconnect_manager

    usuario = user["display_name"]
    username = user["username"]

    cancelled = await disconnect_manager.cancel(channel_id, usuario)
    if cancelled:
        RECONNECTIONS.labels(channel_id=channel_id).inc()
        log_event("websocket_disconnect_cancelled", channel_id=channel_id, usuario=usuario)

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
        {"channel_id": channel_id, "usuario": usuario, "role": user["role"]},
    )

    try:
        while True:
            try:
                data = await websocket.receive_json()
            except json.JSONDecodeError:
                log_event("websocket_malformed_json", channel_id=channel_id, usuario=usuario)
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
        disconnected = await connections.disconnect(channel_id, usuario, websocket)
        if disconnected:
            coro = _finalize_disconnect(
                channel_id,
                usuario,
                disconnect_manager.grace_seconds,
                presence_service,
                pubsub_service,
                audit_publisher,
            )
            disconnect_manager.schedule(channel_id, usuario, coro)
