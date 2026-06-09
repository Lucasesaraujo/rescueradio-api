from fastapi import WebSocket


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
                pass

        await websocket.accept()
        self.connections[channel_id][usuario] = websocket

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
        return True

    def get_active_members(self, channel_id: str) -> list[dict]:
        self.ensure_channel(channel_id)
        return [
            {"usuario": usuario, "status": "online"}
            for usuario in self.connections[channel_id]
        ]

    async def broadcast(self, channel_id: str, message: dict):
        channel_connections = list(
            self.connections.get(channel_id, {}).items()
        )
        disconnected_users = []

        for usuario, connection in channel_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected_users.append(usuario)

        for usuario in disconnected_users:
            self.connections[channel_id].pop(usuario, None)
