import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

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
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

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


@pytest.mark.parametrize("usuario", ["", "   ", "a" * 81])
def test_rejects_invalid_user_during_handshake(usuario):
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(
                f"/ws/channel/canal-geral?usuario={usuario}"
            ):
                pass

        assert error.value.code == 1008
        assert app.state.connections.get_active_members("canal-geral") == []


def test_trims_user_during_handshake():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/channel/canal-geral?usuario=%20Lucas%20"
        ) as websocket:
            connected, _, joined = receive_initial_events(websocket)

            assert connected["usuario"] == "Lucas"
            assert joined["members"] == [
                {"usuario": "Lucas", "status": "online"}
            ]


def test_broadcasts_messages_to_other_members_and_member_disconnect():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

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

                with client.websocket_connect(
                    "/ws/channel/canal-geral?usuario=Julia"
                ) as julia:
                    receive_initial_events(julia)
                    julia_joined_for_lucas = lucas.receive_json()
                    julia_joined_for_marcelo = marcelo.receive_json()
                    assert julia_joined_for_lucas["type"] == "MEMBER_JOINED"
                    assert julia_joined_for_marcelo["type"] == "MEMBER_JOINED"
                    assert len(julia_joined_for_lucas["members"]) == 3

                    lucas.send_json(valid_message())
                    marcelo_message = marcelo.receive_json()
                    julia_message = julia.receive_json()

                    assert marcelo_message["type"] == "MESSAGE_RECEIVED"
                    assert marcelo_message["payload"] == valid_message()
                    assert julia_message == marcelo_message

                julia_left_for_lucas = lucas.receive_json()
                julia_left_for_marcelo = marcelo.receive_json()
                assert julia_left_for_lucas["type"] == "MEMBER_LEFT"
                assert julia_left_for_marcelo["type"] == "MEMBER_LEFT"

            left = lucas.receive_json()
            assert left["type"] == "MEMBER_LEFT"
            assert left["members"] == [
                {"usuario": "Lucas", "status": "online"}
            ]


def test_quick_reconnect_cancels_member_left_event():
    app = create_app(
        udp_host="127.0.0.1",
        udp_port=0,
        disconnect_grace_seconds=0.2,
    )

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/channel/canal-geral?usuario=Lucas"
        ) as lucas:
            receive_initial_events(lucas)

            with client.websocket_connect(
                "/ws/channel/canal-geral?usuario=Marcelo"
            ) as marcelo:
                receive_initial_events(marcelo)
                lucas.receive_json()

            with client.websocket_connect(
                "/ws/channel/canal-geral?usuario=Marcelo"
            ) as marcelo_reconnected:
                connected, briefing, joined = receive_initial_events(
                    marcelo_reconnected
                )
                joined_for_lucas = lucas.receive_json()

                assert connected["usuario"] == "Marcelo"
                assert briefing["type"] == "BRIEFING"
                assert joined["type"] == "MEMBER_JOINED"
                assert joined_for_lucas["type"] == "MEMBER_JOINED"
                assert all(
                    event["type"] != "MEMBER_LEFT"
                    for event in [joined, joined_for_lucas]
                )


def test_includes_previous_messages_in_briefing():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/channel/canal-geral?usuario=Lucas"
        ) as lucas:
            receive_initial_events(lucas)

            with client.websocket_connect(
                "/ws/channel/canal-geral?usuario=Marcelo"
            ) as marcelo:
                receive_initial_events(marcelo)
                lucas.receive_json()
                lucas.send_json(valid_message())
                marcelo.receive_json()

        with client.websocket_connect(
            "/ws/channel/canal-geral?usuario=Julia"
        ) as julia:
            connected = julia.receive_json()
            briefing = julia.receive_json()

            assert connected["type"] == "CONNECTED"
            assert briefing["messages"] == [valid_message()]


def test_briefing_keeps_only_last_50_messages():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/channel/canal-geral?usuario=Lucas"
        ) as lucas:
            receive_initial_events(lucas)

            with client.websocket_connect(
                "/ws/channel/canal-geral?usuario=Marcelo"
            ) as marcelo:
                receive_initial_events(marcelo)
                lucas.receive_json()

                for index in range(51):
                    message = valid_message()
                    message["corpo_texto"] = f"Mensagem {index}"
                    lucas.send_json(message)
                    marcelo.receive_json()

        with client.websocket_connect(
            "/ws/channel/canal-geral?usuario=Julia"
        ) as julia:
            julia.receive_json()
            briefing = julia.receive_json()

            assert len(briefing["messages"]) == 50
            assert briefing["messages"][0]["corpo_texto"] == "Mensagem 1"
            assert briefing["messages"][-1]["corpo_texto"] == "Mensagem 50"


def test_returns_error_for_invalid_payload():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

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


def test_returns_error_for_non_object_payload():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/channel/canal-geral?usuario=Lucas"
        ) as websocket:
            receive_initial_events(websocket)
            websocket.send_json([])

            error = websocket.receive_json()

            assert error["type"] == "ERROR"
            assert error["message"] == "Payload deve ser um objeto JSON"


def test_returns_error_for_malformed_json_and_keeps_connection():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/channel/canal-geral?usuario=Lucas"
        ) as lucas:
            receive_initial_events(lucas)
            lucas.send_text("not-json")

            error = lucas.receive_json()

            assert error == {
                "type": "ERROR",
                "channel_id": "canal-geral",
                "message": "Payload deve conter JSON válido",
            }

            with client.websocket_connect(
                "/ws/channel/canal-geral?usuario=Marcelo"
            ) as marcelo:
                receive_initial_events(marcelo)
                lucas.receive_json()
                lucas.send_json(valid_message())
                received = marcelo.receive_json()

                assert received["type"] == "MESSAGE_RECEIVED"
