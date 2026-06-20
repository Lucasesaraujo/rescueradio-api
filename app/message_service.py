from app.state import ChannelState
from app.validators import validate_incoming_message
from app.websocket_manager import WebSocketConnectionManager, log_event


class MessageService:
    def __init__(
        self,
        channel_state: ChannelState,
        connections: WebSocketConnectionManager,
    ):
        self.channel_state = channel_state
        self.connections = connections

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
        self.channel_state.add_message_to_buffer(channel_id, message)
        recipients = await self.connections.broadcast(
            channel_id,
            {
                "type": "MESSAGE_RECEIVED",
                "channel_id": channel_id,
                "payload": message,
            },
            exclude_usuario=exclude_usuario,
        )
        log_event(
            "message_published",
            channel_id=channel_id,
            usuario=message["usuario"],
            recipients=recipients,
            sender_excluded=exclude_usuario is not None,
        )

        return True, message
