import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from tests.test_auth import BOOTSTRAP_KEY, auth, create_invite


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


def register_and_login(client: TestClient, username: str, display_name: str) -> str:
    bootstrap = client.post(
        "/auth/bootstrap-admin",
        json={
            "username": username,
            "display_name": display_name,
            "password": "segredo123",
            "bootstrap_key": BOOTSTRAP_KEY,
        },
    )
    if bootstrap.status_code == 409:
        admin_token = getattr(client.app.state, "test_admin_token", None)
        if admin_token is None:
            login_admin = client.post(
                "/auth/login",
                json={"username": "lucas", "password": "segredo123"},
            )
            admin_token = login_admin.json().get("access_token")
            client.app.state.test_admin_token = admin_token
        code = create_invite(client, admin_token)
        client.post(
            "/auth/register",
            json={
                "username": username,
                "display_name": display_name,
                "password": "segredo123",
                "invite_code": code,
            },
        )
    elif bootstrap.status_code == 201:
        login_admin = client.post(
            "/auth/login",
            json={"username": username, "password": "segredo123"},
        )
        client.app.state.test_admin_token = login_admin.json()["access_token"]
    response = client.post(
        "/auth/login",
        json={"username": username, "password": "segredo123"},
    )
    return response.json()["access_token"]


def websocket_path(token: str, channel_id: str = "canal-geral") -> str:
    return f"/ws/channel/{channel_id}?token={token}"


def test_connects_with_token_and_receives_empty_briefing():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        token = register_and_login(client, "lucas", "Lucas")

        with client.websocket_connect(websocket_path(token)) as websocket:
            connected, briefing, joined = receive_initial_events(websocket)

            assert connected["type"] == "CONNECTED"
            assert connected["usuario"] == "Lucas"
            assert connected["role"] == "admin"
            assert briefing == {
                "type": "BRIEFING",
                "channel_id": "canal-geral",
                "messages": [],
            }
            assert joined["members"] == [
                {"usuario": "Lucas", "status": "online"}
            ]


def test_rejects_missing_or_invalid_websocket_token():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as missing_error:
            with client.websocket_connect("/ws/channel/canal-geral"):
                pass

        with pytest.raises(WebSocketDisconnect) as invalid_error:
            with client.websocket_connect("/ws/channel/canal-geral?token=invalid"):
                pass

        assert missing_error.value.code == 1008
        assert invalid_error.value.code == 1008
        assert app.state.connections.get_active_members("canal-geral") == []


def test_broadcasts_messages_to_other_members_and_member_disconnect():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        lucas_token = register_and_login(client, "lucas", "Lucas")
        marcelo_token = register_and_login(client, "marcelo", "Marcelo")
        julia_token = register_and_login(client, "julia", "Julia")

        with client.websocket_connect(websocket_path(lucas_token)) as lucas:
            receive_initial_events(lucas)

            with client.websocket_connect(websocket_path(marcelo_token)) as marcelo:
                receive_initial_events(marcelo)
                joined = lucas.receive_json()
                assert joined["type"] == "MEMBER_JOINED"
                assert len(joined["members"]) == 2

                with client.websocket_connect(websocket_path(julia_token)) as julia:
                    receive_initial_events(julia)
                    julia_joined_for_lucas = lucas.receive_json()
                    julia_joined_for_marcelo = marcelo.receive_json()
                    assert julia_joined_for_lucas["type"] == "MEMBER_JOINED"
                    assert julia_joined_for_marcelo["type"] == "MEMBER_JOINED"
                    assert len(julia_joined_for_lucas["members"]) == 3

                    lucas.send_json(valid_message("Tentativa Spoof"))
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


def test_admin_can_clear_channel_messages_and_clients_are_notified():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        admin_token = register_and_login(client, "lucas", "Lucas")
        operator_token = register_and_login(client, "marcelo", "Marcelo")

        with client.websocket_connect(websocket_path(admin_token)) as admin_socket:
            receive_initial_events(admin_socket)
            with client.websocket_connect(websocket_path(operator_token)) as operator_socket:
                receive_initial_events(operator_socket)
                admin_socket.receive_json()  # marcelo entrou

                admin_socket.send_json(valid_message())
                received = operator_socket.receive_json()
                assert received["type"] == "MESSAGE_RECEIVED"

                cleared = client.delete(
                    "/channels/canal-geral/messages",
                    headers=auth(admin_token),
                )
                assert cleared.status_code == 200
                assert cleared.json()["removed"] == 1

                admin_cleared = admin_socket.receive_json()
                operator_cleared = operator_socket.receive_json()
                assert admin_cleared["type"] == "CHAT_CLEARED"
                assert operator_cleared["type"] == "CHAT_CLEARED"

        with client.websocket_connect(websocket_path(operator_token)) as websocket:
            _, briefing, _ = receive_initial_events(websocket)
            assert briefing["messages"] == []


def test_quick_reconnect_cancels_member_left_event():
    app = create_app(
        udp_host="127.0.0.1",
        udp_port=0,
        disconnect_grace_seconds=0.2,
    )

    with TestClient(app) as client:
        lucas_token = register_and_login(client, "lucas", "Lucas")
        marcelo_token = register_and_login(client, "marcelo", "Marcelo")

        with client.websocket_connect(websocket_path(lucas_token)) as lucas:
            receive_initial_events(lucas)

            with client.websocket_connect(websocket_path(marcelo_token)) as marcelo:
                receive_initial_events(marcelo)
                lucas.receive_json()

            with client.websocket_connect(websocket_path(marcelo_token)) as marcelo_reconnected:
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
        lucas_token = register_and_login(client, "lucas", "Lucas")
        marcelo_token = register_and_login(client, "marcelo", "Marcelo")
        julia_token = register_and_login(client, "julia", "Julia")

        with client.websocket_connect(websocket_path(lucas_token)) as lucas:
            receive_initial_events(lucas)

            with client.websocket_connect(websocket_path(marcelo_token)) as marcelo:
                receive_initial_events(marcelo)
                lucas.receive_json()
                lucas.send_json(valid_message())
                marcelo.receive_json()

        with client.websocket_connect(websocket_path(julia_token)) as julia:
            connected = julia.receive_json()
            briefing = julia.receive_json()

            assert connected["type"] == "CONNECTED"
            assert briefing["messages"] == [valid_message()]


def test_briefing_keeps_only_last_50_messages():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        lucas_token = register_and_login(client, "lucas", "Lucas")
        marcelo_token = register_and_login(client, "marcelo", "Marcelo")
        julia_token = register_and_login(client, "julia", "Julia")

        with client.websocket_connect(websocket_path(lucas_token)) as lucas:
            receive_initial_events(lucas)

            with client.websocket_connect(websocket_path(marcelo_token)) as marcelo:
                receive_initial_events(marcelo)
                lucas.receive_json()

                for index in range(51):
                    message = valid_message()
                    message["corpo_texto"] = f"Mensagem {index}"
                    lucas.send_json(message)
                    marcelo.receive_json()

        with client.websocket_connect(websocket_path(julia_token)) as julia:
            julia.receive_json()
            briefing = julia.receive_json()

            assert len(briefing["messages"]) == 50
            assert briefing["messages"][0]["corpo_texto"] == "Mensagem 1"
            assert briefing["messages"][-1]["corpo_texto"] == "Mensagem 50"


def test_returns_error_for_invalid_payload():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        token = register_and_login(client, "lucas", "Lucas")

        with client.websocket_connect(websocket_path(token)) as websocket:
            receive_initial_events(websocket)
            message = valid_message()
            message["type"] = "UNKNOWN"
            websocket.send_json(message)

            error = websocket.receive_json()

            assert error["type"] == "ERROR"
            assert "inv" in error["message"]


def test_returns_error_for_non_object_payload():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        token = register_and_login(client, "lucas", "Lucas")

        with client.websocket_connect(websocket_path(token)) as websocket:
            receive_initial_events(websocket)
            websocket.send_json([])

            error = websocket.receive_json()

            assert error["type"] == "ERROR"
            assert error["message"] == "Payload deve ser um objeto JSON"


def test_returns_error_for_malformed_json_and_keeps_connection():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        lucas_token = register_and_login(client, "lucas", "Lucas")
        marcelo_token = register_and_login(client, "marcelo", "Marcelo")

        with client.websocket_connect(websocket_path(lucas_token)) as lucas:
            receive_initial_events(lucas)
            lucas.send_text("not-json")

            error = lucas.receive_json()

            assert error == {
                "type": "ERROR",
                "channel_id": "canal-geral",
                "message": "Payload deve conter JSON válido",
            }

            with client.websocket_connect(websocket_path(marcelo_token)) as marcelo:
                receive_initial_events(marcelo)
                lucas.receive_json()
                lucas.send_json(valid_message())
                received = marcelo.receive_json()

                assert received["type"] == "MESSAGE_RECEIVED"
