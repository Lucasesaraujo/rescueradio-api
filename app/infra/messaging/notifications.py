import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket


logger = logging.getLogger("rescueradio.notifications")


class NotificationManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, username: str, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections[username].add(websocket)

    async def disconnect(self, username: str, websocket: WebSocket):
        async with self._lock:
            connections = self._connections.get(username)
            if not connections:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop(username, None)

    async def notify(self, username: str, payload: dict):
        async with self._lock:
            targets = list(self._connections.get(username, set()))

        for websocket in targets:
            try:
                await websocket.send_json(payload)
            except Exception:
                logger.exception("failed_to_send_notification", extra={"username": username})
                await self.disconnect(username, websocket)
