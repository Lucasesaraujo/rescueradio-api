import asyncio
import json
import logging

from app.message_service import MessageService
from app.validators import validate_udp_datagram


logger = logging.getLogger(__name__)


class UdpMessageProtocol(asyncio.DatagramProtocol):
    def __init__(self, message_service: MessageService):
        self.message_service = message_service

    def datagram_received(self, data: bytes, addr):
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            logger.warning("Datagrama UDP inválido de %s: %s", addr, error)
            return

        is_valid, result = validate_udp_datagram(payload)

        if not is_valid:
            logger.warning("Datagrama UDP rejeitado de %s: %s", addr, result)
            return

        channel_id, message = result
        asyncio.create_task(self._publish(channel_id, message, addr))

    async def _publish(self, channel_id: str, message: dict, addr):
        is_valid, result = await self.message_service.publish(
            channel_id,
            message,
        )

        if not is_valid:
            logger.warning("Mensagem UDP rejeitada de %s: %s", addr, result)
