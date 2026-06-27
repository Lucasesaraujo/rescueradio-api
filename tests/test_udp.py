import asyncio
import json
import socket

from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_websocket import receive_initial_events, register_and_login, websocket_path


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


async def wait_for_briefing(
    app,
    channel_id: str,
    expected_size: int,
    timeout: float = 1.0,
):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    while loop.time() < deadline:
        briefing = await app.state.message_repository.get_briefing(channel_id)

        if len(briefing) == expected_size:
            return briefing

        await asyncio.sleep(0.01)

    raise AssertionError(
        f"Briefing de {channel_id} nao atingiu {expected_size} mensagem(ns)"
    )


def test_forwards_udp_message_to_websocket_client():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        token = register_and_login(client, "lucas", "Lucas")

        with client.websocket_connect(websocket_path(token)) as websocket:
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
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        send_datagram(app.state.udp_port, b"not-json")
        send_datagram(
            app.state.udp_port,
            json.dumps({"type": "SEND_MESSAGE"}).encode("utf-8"),
        )
        send_datagram(
            app.state.udp_port,
            json.dumps([]).encode("utf-8"),
        )

        briefing = client.portal.call(
            app.state.message_repository.get_briefing,
            "canal-geral",
        )

        assert briefing == []


def test_keeps_udp_messages_isolated_by_channel():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        send_datagram(
            app.state.udp_port,
            json.dumps(udp_message("canal-alfa")).encode("utf-8"),
        )
        briefing = client.portal.call(
            wait_for_briefing,
            app,
            "canal-alfa",
            1,
        )

        canal_geral_briefing = client.portal.call(
            app.state.message_repository.get_briefing,
            "canal-geral",
        )

        assert canal_geral_briefing == []
        assert len(briefing) == 1
        assert briefing[0]["usuario"] == "Central"


def test_drops_datagram_when_queue_is_full(caplog):
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app):
        protocol = app.state.udp_protocol
        protocol.queue = protocol.queue.__class__(maxsize=1)
        protocol.queue.put_nowait(("canal-geral", {}, ("127.0.0.1", 1234)))

        protocol.datagram_received(
            json.dumps(udp_message()).encode("utf-8"),
            ("127.0.0.1", 1234),
        )

        assert "fila de publicacao cheia" in caplog.text
