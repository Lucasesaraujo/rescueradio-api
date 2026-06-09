import json
import socket
import time

from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_websocket import receive_initial_events


def udp_message(channel_id: str = "canal-geral") -> dict:
    return {
        "type": "SEND_MESSAGE",
        "channel_id": channel_id,
        "usuario": "Central",
        "timestamp_iso": "2026-06-09T12:00:00Z",
        "corpo_texto": "Mensagem recebida por UDP.",
    }


def send_datagram(port: int, payload: bytes):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
        udp_socket.sendto(payload, ("127.0.0.1", port))


def test_forwards_udp_message_to_websocket_client():
    app = create_app(udp_host="127.0.0.1", udp_port=0)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/channel/canal-geral?usuario=Lucas"
        ) as websocket:
            receive_initial_events(websocket)
            send_datagram(
                app.state.udp_port,
                json.dumps(udp_message()).encode("utf-8"),
            )

            event = websocket.receive_json()

            assert event["type"] == "MESSAGE_RECEIVED"
            assert event["channel_id"] == "canal-geral"
            assert event["payload"]["usuario"] == "Central"
            assert "channel_id" not in event["payload"]


def test_discards_invalid_udp_datagram():
    app = create_app(udp_host="127.0.0.1", udp_port=0)

    with TestClient(app):
        send_datagram(app.state.udp_port, b"not-json")
        send_datagram(
            app.state.udp_port,
            json.dumps({"type": "SEND_MESSAGE"}).encode("utf-8"),
        )
        time.sleep(0.1)

        assert app.state.channel_state.get_briefing("canal-geral") == []


def test_keeps_udp_messages_isolated_by_channel():
    app = create_app(udp_host="127.0.0.1", udp_port=0)

    with TestClient(app):
        send_datagram(
            app.state.udp_port,
            json.dumps(udp_message("canal-alfa")).encode("utf-8"),
        )
        time.sleep(0.1)

        assert app.state.channel_state.get_briefing("canal-geral") == []
        briefing = app.state.channel_state.get_briefing("canal-alfa")
        assert len(briefing) == 1
        assert briefing[0]["usuario"] == "Central"
