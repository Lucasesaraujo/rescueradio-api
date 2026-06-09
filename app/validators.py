from datetime import datetime

from pydantic import ValidationError

from app.schemas import IncomingMessage, UdpDatagram


ALLOWED_MESSAGE_TYPES = {
    "SEND_MESSAGE"
}


def validate_incoming_message(data: dict) -> tuple[bool, dict | str]:
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
    data: dict,
) -> tuple[bool, tuple[str, dict] | str]:
    try:
        datagram = UdpDatagram(**data)
    except ValidationError as error:
        return False, str(error)

    message_data = datagram.model_dump(exclude={"channel_id"})
    is_valid, result = validate_incoming_message(message_data)

    if not is_valid:
        return False, result

    return True, (datagram.channel_id, result)
