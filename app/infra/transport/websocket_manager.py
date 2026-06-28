import asyncio

from fastapi import WebSocket

from app.logging import log_event
from app.infra.observability.metrics import ACTIVE_CONNECTIONS


class WebSocketConnectionManager:
    def __init__(self):
        self.connections: dict[str, dict[str, WebSocket]] = {}
        self.lock = asyncio.Lock()

    def ensure_channel(self, channel_id: str):
        if channel_id not in self.connections:
            self.connections[channel_id] = {}

    async def connect(
        self,
        channel_id: str,
        usuario: str,
        websocket: WebSocket,
    ):
        async with self.lock:
            self.ensure_channel(channel_id)
            old_connection = self.connections[channel_id].get(usuario)

        if old_connection is not None:
            try:
                await old_connection.close()
            except Exception:
                log_event(
                    "websocket_replaced_close_failed",
                    channel_id=channel_id,
                    usuario=usuario,
                )

        await websocket.accept()
        async with self.lock:
            self.ensure_channel(channel_id)
            self.connections[channel_id][usuario] = websocket
            active_connections = len(self.connections[channel_id])
            ACTIVE_CONNECTIONS.labels(channel_id=channel_id).set(active_connections)

        log_event(
            "websocket_connected",
            channel_id=channel_id,
            usuario=usuario,
            active_connections=active_connections,
        )

    async def disconnect(
        self,
        channel_id: str,
        usuario: str,
        websocket: WebSocket,
    ) -> bool:
        async with self.lock:
            current_connection = self.connections.get(channel_id, {}).get(usuario)

            if current_connection != websocket:
                return False

            self.connections[channel_id].pop(usuario, None)
            active_connections = len(self.connections[channel_id])
            ACTIVE_CONNECTIONS.labels(channel_id=channel_id).set(active_connections)

        log_event(
            "websocket_disconnected",
            channel_id=channel_id,
            usuario=usuario,
            active_connections=active_connections,
        )
        return True

    def get_active_members(self, channel_id: str) -> list[dict]:
        self.ensure_channel(channel_id)
        return [
            {"usuario": usuario, "status": "online"}
            for usuario in self.connections[channel_id]
        ]

    async def broadcast(
        self,
        channel_id: str,
        message: dict,
        exclude_usuario: str | None = None,
    ) -> int:
        async with self.lock:
            channel_connections = list(
                self.connections.get(channel_id, {}).items()
            )
        disconnected_users = []
        sent_count = 0

        for usuario, connection in channel_connections:
            if usuario == exclude_usuario:
                continue

            try:
                await connection.send_json(message)
                sent_count += 1
            except Exception:
                disconnected_users.append(usuario)

        for usuario in disconnected_users:
            async with self.lock:
                self.connections.get(channel_id, {}).pop(usuario, None)
                active_connections = len(self.connections.get(channel_id, {}))
                ACTIVE_CONNECTIONS.labels(channel_id=channel_id).set(
                    active_connections
                )

            log_event(
                "websocket_removed_broken_connection",
                channel_id=channel_id,
                usuario=usuario,
                active_connections=active_connections,
            )

        log_event(
            "websocket_broadcast",
            channel_id=channel_id,
            message_type=message.get("type"),
            recipients=sent_count,
            skipped_usuario=exclude_usuario,
            removed_connections=len(disconnected_users),
        )
        return sent_count
