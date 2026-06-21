import json
import logging

from fastapi import WebSocket


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def log_event(event: str, **fields):
    logger.info(
        json.dumps(
            {"event": event, **fields},
            ensure_ascii=False,
            sort_keys=True,
        )
    )


class WebSocketConnectionManager:
    def __init__(self):
        self.connections: dict[str, dict[str, WebSocket]] = {}

    def ensure_channel(self, channel_id: str):
        if channel_id not in self.connections:
            self.connections[channel_id] = {}

    async def connect(
        self,
        channel_id: str,
        usuario: str,
        websocket: WebSocket,
    ):
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
        self.connections[channel_id][usuario] = websocket
        log_event(
            "websocket_connected",
            channel_id=channel_id,
            usuario=usuario,
            active_connections=len(self.connections[channel_id]),
        )

    def disconnect(
        self,
        channel_id: str,
        usuario: str,
        websocket: WebSocket,
    ) -> bool:
        current_connection = self.connections.get(channel_id, {}).get(usuario)

        if current_connection != websocket:
            return False

        self.connections[channel_id].pop(usuario, None)
        log_event(
            "websocket_disconnected",
            channel_id=channel_id,
            usuario=usuario,
            active_connections=len(self.connections[channel_id]),
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
            self.connections[channel_id].pop(usuario, None)
            log_event(
                "websocket_removed_broken_connection",
                channel_id=channel_id,
                usuario=usuario,
                active_connections=len(self.connections[channel_id]),
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
