from fastapi.testclient import TestClient

from app.main import create_app


def receive_initial_events(websocket):
    connected = websocket.receive_json()
    briefing = websocket.receive_json()
    joined = websocket.receive_json()
    return connected, briefing, joined


def valid_message(usuario: str = "Lucas") -> dict:
    return {
        "type": "SEND_MESSAGE",
        "usuario": usuario,
        "timestamp_iso": "2026-06-09T12:00:00Z",
        "corpo_texto": "Equipe Alfa chegou ao local.",
    }


def test_connects_and_receives_empty_briefing():
    app = create_app(udp_host="127.0.0.1", udp_port=0)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/channel/canal-geral?usuario=Lucas"
        ) as websocket:
            connected, briefing, joined = receive_initial_events(websocket)

            assert connected["type"] == "CONNECTED"
            assert briefing == {
                "type": "BRIEFING",
                "channel_id": "canal-geral",
                "messages": [],
            }
            assert joined["members"] == [
                {"usuario": "Lucas", "status": "online"}
            ]


def test_broadcasts_messages_and_member_disconnect():
    app = create_app(udp_host="127.0.0.1", udp_port=0)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/channel/canal-geral?usuario=Lucas"
        ) as lucas:
            receive_initial_events(lucas)

            with client.websocket_connect(
                "/ws/channel/canal-geral?usuario=Marcelo"
            ) as marcelo:
                receive_initial_events(marcelo)
                joined = lucas.receive_json()
                assert joined["type"] == "MEMBER_JOINED"
                assert len(joined["members"]) == 2

                lucas.send_json(valid_message())
                lucas_message = lucas.receive_json()
                marcelo_message = marcelo.receive_json()

                assert lucas_message["type"] == "MESSAGE_RECEIVED"
                assert marcelo_message == lucas_message

            left = lucas.receive_json()
            assert left["type"] == "MEMBER_LEFT"
            assert left["members"] == [
                {"usuario": "Lucas", "status": "online"}
            ]


def test_includes_previous_messages_in_briefing():
    app = create_app(udp_host="127.0.0.1", udp_port=0)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/channel/canal-geral?usuario=Lucas"
        ) as lucas:
            receive_initial_events(lucas)
            lucas.send_json(valid_message())
            lucas.receive_json()

        with client.websocket_connect(
            "/ws/channel/canal-geral?usuario=Julia"
        ) as julia:
            connected = julia.receive_json()
            briefing = julia.receive_json()

            assert connected["type"] == "CONNECTED"
            assert briefing["messages"] == [valid_message()]


def test_returns_error_for_invalid_payload():
    app = create_app(udp_host="127.0.0.1", udp_port=0)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/channel/canal-geral?usuario=Lucas"
        ) as websocket:
            receive_initial_events(websocket)
            message = valid_message()
            message["type"] = "UNKNOWN"
            websocket.send_json(message)

            error = websocket.receive_json()

            assert error["type"] == "ERROR"
            assert "inválido" in error["message"]
