import asyncio
import json
import logging

from app.services.message_service import MessageService
from app.infra.observability.metrics import UDP_EVENTS
from app.domain.validators import validate_udp_datagram


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
            UDP_EVENTS.labels(result="invalid_json").inc()
            logger.warning("Datagrama UDP invalido de %s: %s", addr, error)
            return

        is_valid, result = validate_udp_datagram(payload)

        if not is_valid:
            UDP_EVENTS.labels(result="rejected").inc()
            logger.warning("Datagrama UDP rejeitado de %s: %s", addr, result)
            return

        channel_id, message = result

        try:
            self.queue.put_nowait((channel_id, message, addr))
        except asyncio.QueueFull:
            UDP_EVENTS.labels(result="queue_full").inc()
            logger.warning(
                "Datagrama UDP descartado de %s: fila de publicacao cheia",
                addr,
            )

    async def _worker(self):
        while True:
            channel_id, message, addr = await self.queue.get()

            try:
                is_valid, result = await self.message_service.publish(
                    channel_id,
                    message,
                    source="udp",
                )

                if not is_valid:
                    UDP_EVENTS.labels(result="rejected_message").inc()
                    logger.warning(
                        "Mensagem UDP rejeitada de %s: %s",
                        addr,
                        result,
                    )
                else:
                    UDP_EVENTS.labels(result="published").inc()
            except Exception:
                logger.exception(
                    "Falha inesperada ao publicar datagrama UDP de %s",
                    addr,
                )
            finally:
                self.queue.task_done()
