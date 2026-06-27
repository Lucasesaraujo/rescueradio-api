from app.audit import AuditPublisher, NoopAuditPublisher
from app.metrics import KAFKA_FAILURES, MESSAGES_PUBLISHED
from app.state import MessageRepository
from app.pubsub import PubSubService
from app.validators import validate_incoming_message
from app.websocket_manager import log_event


class MessageService:
    def __init__(
        self,
        message_repository: MessageRepository,
        pubsub: PubSubService,
        audit_publisher: AuditPublisher | None = None,
        channel_accepts_messages=None,
    ):
        self.message_repository = message_repository
        self.pubsub = pubsub
        self.audit_publisher = audit_publisher or NoopAuditPublisher()
        self.channel_accepts_messages = channel_accepts_messages

    async def publish(
        self,
        channel_id: str,
        data: object,
        exclude_usuario: str | None = None,
        source: str = "websocket",
    ) -> tuple[bool, dict | str]:
        if self.channel_accepts_messages is not None:
            accepts_message = await self.channel_accepts_messages(channel_id)
            if not accepts_message:
                return False, "Canal de operacao finalizada nao aceita novas mensagens"

        is_valid, result = validate_incoming_message(data)

        if not is_valid:
            log_event(
                "message_rejected",
                channel_id=channel_id,
                reason=str(result),
            )
            return False, result

        message = result
        await self.message_repository.add_message(channel_id, message)
        await self.pubsub.publish_message(
            channel_id,
            {
                "type": "MESSAGE_RECEIVED",
                "channel_id": channel_id,
                "payload": message,
            },
            exclude_usuario=exclude_usuario,
        )
        try:
            await self.audit_publisher.publish(
                "message_published",
                {
                    "channel_id": channel_id,
                    "usuario": message["usuario"],
                    "source": source,
                },
            )
        except Exception:
            KAFKA_FAILURES.inc()
            log_event(
                "audit_publish_failed",
                channel_id=channel_id,
                usuario=message["usuario"],
                source=source,
            )
        MESSAGES_PUBLISHED.labels(channel_id=channel_id, source=source).inc()
        
        log_event(
            "message_published_pubsub",
            channel_id=channel_id,
            usuario=message["usuario"],
            sender_excluded=exclude_usuario is not None,
            source=source,
        )

        return True, message
