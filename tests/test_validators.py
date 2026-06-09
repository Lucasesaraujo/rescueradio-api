from app.validators import validate_incoming_message, validate_udp_datagram


def valid_message() -> dict:
    return {
        "type": "SEND_MESSAGE",
        "usuario": "Lucas",
        "timestamp_iso": "2026-06-04T21:30:00Z",
        "corpo_texto": "Equipe Alfa chegou ao ponto de encontro.",
    }


def test_accepts_valid_message():
    is_valid, result = validate_incoming_message(valid_message())

    assert is_valid is True
    assert result["type"] == "SEND_MESSAGE"


def test_rejects_unknown_message_type():
    message = valid_message()
    message["type"] = "UNKNOWN"

    is_valid, result = validate_incoming_message(message)

    assert is_valid is False
    assert "inválido" in result


def test_rejects_invalid_timestamp():
    message = valid_message()
    message["timestamp_iso"] = "not-a-date"

    is_valid, result = validate_incoming_message(message)

    assert is_valid is False
    assert result == "timestamp_iso deve estar no formato ISO 8601"


def test_accepts_udp_datagram_with_channel():
    message = valid_message()
    message["channel_id"] = "canal-geral"

    is_valid, result = validate_udp_datagram(message)

    assert is_valid is True
    channel_id, validated_message = result
    assert channel_id == "canal-geral"
    assert "channel_id" not in validated_message
