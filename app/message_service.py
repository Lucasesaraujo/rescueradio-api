from app.state import MessageRepository
from app.pubsub import PubSubService
from app.validators import validate_incoming_message
from app.websocket_manager import log_event


class MessageService:
    def __init__(
        self,
        message_repository: MessageRepository,
        pubsub: PubSubService,
    ):
        self.message_repository = message_repository
        self.pubsub = pubsub

    async def publish(
        self,
        channel_id: str,
        data: object,
        exclude_usuario: str | None = None,
    ) -> tuple[bool, dict | str]:
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
        
        log_event(
            "message_published_pubsub",
            channel_id=channel_id,
            usuario=message["usuario"],
            sender_excluded=exclude_usuario is not None,
        )

        return True, message
