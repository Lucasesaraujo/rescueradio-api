import json

from app.terminal_client import (
    build_websocket_url,
    create_message,
    format_server_event,
)


def test_build_websocket_url_encodes_channel_and_user():
    url = build_websocket_url(
        "ws://localhost:8001/",
        "canal geral",
        "Ana Maria",
    )

    assert url == "ws://localhost:8001/ws/channel/canal%20geral?usuario=Ana%20Maria"


def test_create_message_uses_send_message_contract():
    message = create_message("Lucas", "Cheguei ao local.")

    assert message["type"] == "SEND_MESSAGE"
    assert message["usuario"] == "Lucas"
    assert message["corpo_texto"] == "Cheguei ao local."
    assert "timestamp_iso" in message


def test_format_server_event_shows_received_message_for_terminal():
    event = {
        "type": "MESSAGE_RECEIVED",
        "channel_id": "canal-geral",
        "payload": {
            "usuario": "Marcelo",
            "corpo_texto": "Equipe Alfa pronta.",
        },
    }

    formatted = format_server_event(json.dumps(event))

    assert formatted == "[canal-geral] Marcelo: Equipe Alfa pronta."
