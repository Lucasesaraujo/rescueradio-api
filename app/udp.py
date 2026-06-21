import asyncio
import json
import logging

from app.message_service import MessageService
from app.validators import validate_udp_datagram


logger = logging.getLogger(__name__)
UDP_QUEUE_SIZE = 100


class UdpMessageProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        message_service: MessageService,
        queue_size: int = UDP_QUEUE_SIZE,
    ):
        self.message_service = message_service
        self.queue: asyncio.Queue[tuple[str, dict, object]] = asyncio.Queue(
            maxsize=queue_size
        )
        self.worker_task: asyncio.Task | None = None

    def connection_made(self, transport):
        self.worker_task = asyncio.create_task(self._worker())

    def connection_lost(self, exc):
        if self.worker_task is not None:
            self.worker_task.cancel()

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

        try:
            self.queue.put_nowait((channel_id, message, addr))
        except asyncio.QueueFull:
            logger.warning(
                "Datagrama UDP descartado de %s: fila de publicação cheia",
                addr,
            )

    async def _worker(self):
        while True:
            channel_id, message, addr = await self.queue.get()

            try:
                is_valid, result = await self.message_service.publish(
                    channel_id,
                    message,
                )

                if not is_valid:
                    logger.warning(
                        "Mensagem UDP rejeitada de %s: %s",
                        addr,
                        result,
                    )
            except Exception:
                logger.exception(
                    "Falha inesperada ao publicar datagrama UDP de %s",
                    addr,
                )
            finally:
                self.queue.task_done()
