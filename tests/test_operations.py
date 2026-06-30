from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_auth import BOOTSTRAP_KEY, create_invite
from tests.test_websocket import receive_initial_events, websocket_path


def register_login(client: TestClient, username: str, display_name: str) -> str:
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
            admin_login = client.post(
                "/auth/login",
                json={"username": "admin", "password": "segredo123"},
            )
            admin_token = admin_login.json().get("access_token")
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
        admin_login = client.post(
            "/auth/login",
            json={"username": username, "password": "segredo123"},
        )
        client.app.state.test_admin_token = admin_login.json()["access_token"]
    response = client.post(
        "/auth/login",
        json={"username": username, "password": "segredo123"},
    )
    return response.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def profile_payload(base_id: str = "base-central") -> dict:
    return {
        "operational_name": "Lucas",
        "base_id": base_id,
        "function": "Resgate",
        "contact": "Radio 01",
        "status": "disponivel",
        "skills": ["APH", "Busca"],
    }


def occurrence_payload() -> dict:
    return {
        "base_id": "base-central",
        "title": "Resgate em area alagada",
        "type": "resgate",
        "priority": "critico",
        "address_text": "Marco Zero, Recife",
        "latitude": -8.063,
        "longitude": -34.871,
        "description": "Vitimas ilhadas aguardando remocao.",
    }


def test_profile_onboarding_and_operator_listing():
    app = create_app(udp_host="127.0.0.1", udp_port=0)

    with TestClient(app) as client:
        token = register_login(client, "lucas", "Lucas")

        bases = client.get("/bases", headers=auth(token))
        assert bases.status_code == 200
        assert bases.json()[0]["id"] == "base-central"

        me = client.get("/profiles/me", headers=auth(token))
        assert me.json()["complete"] is False

        profile = client.put("/profiles/me", json=profile_payload(), headers=auth(token))
        assert profile.status_code == 200
        assert profile.json()["skills"] == ["APH", "Busca"]

        operators = client.get("/operators?base_id=base-central", headers=auth(token))
        assert operators.status_code == 200
        assert operators.json()[0]["username"] == "lucas"


def test_admin_promotes_user_and_commander_creates_and_closes_operation():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        admin_token = register_login(client, "admin", "Admin")
        commander_token = register_login(client, "cmd", "Comandante")
        operator_token = register_login(client, "op", "Operador")

        promote = client.patch(
            "/users/cmd/role",
            json={"role": "comandante", "uf_scope": "PE"},
            headers=auth(admin_token),
        )
        assert promote.status_code == 200
        assert promote.json()["role"] == "comandante"

        client.put("/profiles/me", json=profile_payload(), headers=auth(operator_token))

        created = client.post(
            "/operations",
            json={
                "occurrence": occurrence_payload(),
                "member_usernames": ["op"],
            },
            headers=auth(commander_token),
        )
        assert created.status_code == 201
        operation = created.json()
        assert operation["status"] == "active"
        assert operation["channel_id"].startswith("operacao:")
        assert operation["members"][0]["username"] == "op"

        close = client.post(
            f"/operations/{operation['id']}/close",
            json={"summary": "Vitimas removidas e area isolada.", "outcome": "success"},
            headers=auth(commander_token),
        )
        assert close.status_code == 200
        assert close.json()["status"] == "closed"
        assert close.json()["outcome"] == "success"

        audit = client.get(f"/operations/{operation['id']}/audit", headers=auth(admin_token))
        assert audit.status_code == 200
        assert audit.json()["operation"]["closing_summary"] == "Vitimas removidas e area isolada."
        assert audit.json()["operation"]["outcome"] == "success"
        assert audit.json()["status_events"][-1]["status"] == "closed"


def test_operator_cannot_create_operation_and_closed_operation_chat_rejects_messages():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        admin_token = register_login(client, "admin", "Admin")
        operator_token = register_login(client, "op", "Operador")

        forbidden = client.post(
            "/operations",
            json={"occurrence": occurrence_payload(), "member_usernames": []},
            headers=auth(operator_token),
        )
        assert forbidden.status_code == 403

        created = client.post(
            "/operations",
            json={"occurrence": occurrence_payload(), "member_usernames": ["op"]},
            headers=auth(admin_token),
        ).json()
        client.post(
            f"/operations/{created['id']}/close",
            json={"summary": "Encerrada para teste.", "outcome": "failure"},
            headers=auth(admin_token),
        )

        with client.websocket_connect(websocket_path(operator_token, created["channel_id"])) as websocket:
            receive_initial_events(websocket)
            websocket.send_json(
                {
                    "type": "SEND_MESSAGE",
                    "usuario": "Operador",
                    "timestamp_iso": "2026-06-09T12:00:00Z",
                    "corpo_texto": "Mensagem tardia.",
                }
            )
            error = websocket.receive_json()

            assert error["type"] == "ERROR"
            assert "finalizada" in error["message"]


def test_notification_websocket_receives_assignment_event():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        admin_token = register_login(client, "admin", "Admin")
        operator_token = register_login(client, "op", "Operador")
        client.put("/profiles/me", json=profile_payload(), headers=auth(operator_token))

        with client.websocket_connect(f"/ws/notifications?token={operator_token}") as websocket:
            connected = websocket.receive_json()
            assert connected["type"] == "NOTIFICATIONS_CONNECTED"

            created = client.post(
                "/operations",
                json={"occurrence": occurrence_payload(), "member_usernames": ["op"]},
                headers=auth(admin_token),
            )
            assert created.status_code == 201
            event = websocket.receive_json()
            assert event["type"] == "OPERATION_ASSIGNED"
            assert event["operation_id"] == created.json()["id"]


def test_operator_assignment_acknowledgement_persists_server_side():
    app = create_app(udp_host="127.0.0.1", udp_port=0, disconnect_grace_seconds=0)

    with TestClient(app) as client:
        admin_token = register_login(client, "admin", "Admin")
        operator_token = register_login(client, "op", "Operador")
        client.put("/profiles/me", json=profile_payload(), headers=auth(operator_token))

        created = client.post(
            "/operations",
            json={"occurrence": occurrence_payload(), "member_usernames": ["op"]},
            headers=auth(admin_token),
        )
        operation_id = created.json()["id"]

        before = client.get(
            f"/operations/{operation_id}/assignment-ack",
            headers=auth(operator_token),
        )
        assert before.status_code == 200
        assert before.json()["acknowledged"] is False

        ack = client.post(
            f"/operations/{operation_id}/assignment-ack",
            headers=auth(operator_token),
        )
        assert ack.status_code == 200
        assert ack.json()["acknowledged"] is True

        after = client.get(
            f"/operations/{operation_id}/assignment-ack",
            headers=auth(operator_token),
        )
        assert after.status_code == 200
        assert after.json()["acknowledged"] is True
