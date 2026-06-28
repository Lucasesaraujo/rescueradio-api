import asyncio
import json
import logging
from typing import Protocol

from app.infra.transport.websocket_manager import WebSocketConnectionManager

logger = logging.getLogger(__name__)


class PubSubService(Protocol):
    async def publish_message(self, channel_id: str, message: dict, exclude_usuario: str | None = None):
        ...

    async def start_listening(self):
        ...

    async def stop_listening(self):
        ...


class InMemoryPubSubService:
    def __init__(self, connections: WebSocketConnectionManager):
        self.connections = connections

    async def publish_message(self, channel_id: str, message: dict, exclude_usuario: str | None = None):
        await self.connections.broadcast(channel_id, message, exclude_usuario=exclude_usuario)

    async def start_listening(self):
        pass

    async def stop_listening(self):
        pass


class RedisPubSubService:
    def __init__(self, redis_url: str, connections: WebSocketConnectionManager):
        from redis.asyncio import Redis

        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.pubsub = self.redis.pubsub()
        self.connections = connections
        self.listen_task: asyncio.Task | None = None

    async def publish_message(self, channel_id: str, message: dict, exclude_usuario: str | None = None):
        payload = {
            "channel_id": channel_id,
            "message": message,
            "exclude_usuario": exclude_usuario
        }
        await self.redis.publish("rescueradio:broadcast", json.dumps(payload, ensure_ascii=False))

    async def start_listening(self):
        await self.pubsub.subscribe("rescueradio:broadcast")
        self.listen_task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        try:
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    channel_id = data["channel_id"]
                    msg_payload = data["message"]
                    exclude_usuario = data.get("exclude_usuario")

                    await self.connections.broadcast(
                        channel_id,
                        msg_payload,
                        exclude_usuario=exclude_usuario
                    )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Redis PubSub listener error: {e}")

    async def stop_listening(self):
        if self.listen_task:
            self.listen_task.cancel()
        await self.pubsub.close()
        await self.redis.aclose()
