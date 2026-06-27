import json
import logging
import os
from datetime import datetime, timezone
from typing import Protocol

from app.metrics import KAFKA_FAILURES


logger = logging.getLogger(__name__)


class AuditPublisher(Protocol):
    async def start(self):
        ...

    async def publish(self, event_type: str, payload: dict):
        ...

    async def stop(self):
        ...


class NoopAuditPublisher:
    async def start(self):
        return None

    async def publish(self, event_type: str, payload: dict):
        return None

    async def stop(self):
        return None


class KafkaAuditPublisher:
    def __init__(self, bootstrap_servers: str, topic: str = "rescueradio.audit"):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.producer = None

    async def start(self):
        try:
            from aiokafka import AIOKafkaProducer

            self.producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda value: json.dumps(
                    value,
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            await self.producer.start()
        except Exception:
            self.producer = None
            KAFKA_FAILURES.inc()
            logger.exception("Falha ao iniciar producer Kafka de auditoria")

    async def publish(self, event_type: str, payload: dict):
        if self.producer is None:
            return

        event = {
            "event_type": event_type,
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }

        try:
            await self.producer.send_and_wait(self.topic, event)
        except Exception:
            KAFKA_FAILURES.inc()
            logger.exception("Falha ao publicar evento de auditoria no Kafka")

    async def stop(self):
        if self.producer is not None:
            await self.producer.stop()


def create_audit_publisher() -> AuditPublisher:
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "").strip()

    if not bootstrap_servers:
        return NoopAuditPublisher()

    return KafkaAuditPublisher(
        bootstrap_servers,
        os.getenv("KAFKA_AUDIT_TOPIC", "rescueradio.audit"),
    )
