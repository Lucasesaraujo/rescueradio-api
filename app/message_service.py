from app.state import ChannelState
from app.validators import validate_incoming_message
from app.websocket_manager import WebSocketConnectionManager


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
        data: dict,
    ) -> tuple[bool, dict | str]:
        is_valid, result = validate_incoming_message(data)

        if not is_valid:
            return False, result

        message = result
        self.channel_state.add_message_to_buffer(channel_id, message)
        await self.connections.broadcast(channel_id, {
            "type": "MESSAGE_RECEIVED",
            "channel_id": channel_id,
            "payload": message,
        })

        return True, message
