from datetime import datetime

from pydantic import ValidationError

from app.domain.schemas import IncomingMessage, UdpDatagram


ALLOWED_MESSAGE_TYPES = {
    "SEND_MESSAGE"
}


def validate_incoming_message(data: object) -> tuple[bool, dict | str]:
    if not isinstance(data, dict):
        return False, "Payload deve ser um objeto JSON"

    try:
        message = IncomingMessage(**data)
    except ValidationError as error:
        return False, str(error)

    if message.type not in ALLOWED_MESSAGE_TYPES:
        return False, f"Tipo de mensagem inválido: {message.type}"

    try:
        datetime.fromisoformat(message.timestamp_iso.replace("Z", "+00:00"))
    except ValueError:
        return False, "timestamp_iso deve estar no formato ISO 8601"

    return True, message.model_dump()


def validate_udp_datagram(
    data: object,
) -> tuple[bool, tuple[str, dict] | str]:
    if not isinstance(data, dict):
        return False, "Datagrama deve ser um objeto JSON"

    try:
        datagram = UdpDatagram(**data)
    except (TypeError, ValidationError) as error:
        return False, str(error)

    message_data = {
        key: value
        for key, value in data.items()
        if key != "channel_id"
    }
    return True, (datagram.channel_id, message_data)
