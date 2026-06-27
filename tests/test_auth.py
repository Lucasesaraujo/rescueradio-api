from fastapi.testclient import TestClient

from app.main import create_app


BOOTSTRAP_KEY = "rescueradio-bootstrap"


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def bootstrap_admin(client: TestClient, username: str = "admin") -> str:
    response = client.post(
        "/auth/bootstrap-admin",
        json={
            "username": username,
            "display_name": "Admin",
            "password": "segredo123",
            "bootstrap_key": BOOTSTRAP_KEY,
        },
    )
    assert response.status_code == 201
    login = client.post("/auth/login", json={"username": username, "password": "segredo123"})
    return login.json()["access_token"]


def create_invite(client: TestClient, admin_token: str, role: str = "operador") -> str:
    response = client.post(
        "/invites",
        json={"base_id": "base-central", "role": role, "expires_in_hours": 24},
        headers=auth(admin_token),
    )
    assert response.status_code == 201
    return response.json()["code"]


def test_bootstrap_admin_and_invite_registration():
    app = create_app(udp_host="127.0.0.1", udp_port=0)

    with TestClient(app) as client:
        admin_token = bootstrap_admin(client)
        code = create_invite(client, admin_token)
        created = client.post(
            "/auth/register",
            json={
                "username": "lucas",
                "display_name": "Lucas",
                "password": "segredo123",
                "invite_code": code,
            },
        )

        assert created.status_code == 201
        assert created.json()["role"] == "operador"


def test_rejects_open_registration_and_reused_invite():
    app = create_app(udp_host="127.0.0.1", udp_port=0)

    with TestClient(app) as client:
        admin_token = bootstrap_admin(client)
        payload = {
            "username": "lucas",
            "display_name": "Lucas",
            "password": "segredo123",
            "invite_code": "invalido123",
        }
        assert client.post("/auth/register", json=payload).status_code == 403

        payload["invite_code"] = create_invite(client, admin_token)
        assert client.post("/auth/register", json=payload).status_code == 201
        payload["username"] = "marcelo"
        assert client.post("/auth/register", json=payload).status_code == 403


def test_bootstrap_is_blocked_after_admin_exists_and_invalid_key_fails():
    app = create_app(udp_host="127.0.0.1", udp_port=0)

    with TestClient(app) as client:
        invalid = client.post(
            "/auth/bootstrap-admin",
            json={
                "username": "bad",
                "display_name": "Bad",
                "password": "segredo123",
                "bootstrap_key": "errada",
            },
        )
        assert invalid.status_code == 403
        bootstrap_admin(client)
        blocked = client.post(
            "/auth/bootstrap-admin",
            json={
                "username": "admin2",
                "display_name": "Admin 2",
                "password": "segredo123",
                "bootstrap_key": BOOTSTRAP_KEY,
            },
        )
        assert blocked.status_code == 409


def test_login_returns_token_and_me_returns_current_user():
    app = create_app(udp_host="127.0.0.1", udp_port=0)

    with TestClient(app) as client:
        token = bootstrap_admin(client, "julia")

        me = client.get("/auth/me", headers=auth(token))

        assert me.status_code == 200
        assert me.json()["username"] == "julia"
        assert me.json()["display_name"] == "Admin"


def test_admin_can_delete_user_but_not_self():
    app = create_app(udp_host="127.0.0.1", udp_port=0)

    with TestClient(app) as client:
        admin_token = bootstrap_admin(client)
        code = create_invite(client, admin_token)
        created = client.post(
            "/auth/register",
            json={
                "username": "operador1",
                "display_name": "Operador 1",
                "password": "segredo123",
                "invite_code": code,
            },
        )
        assert created.status_code == 201

        deleted = client.delete("/users/operador1", headers=auth(admin_token))
        assert deleted.status_code == 204
        users = client.get("/users", headers=auth(admin_token))
        assert "operador1" not in [user["username"] for user in users.json()]

        self_delete = client.delete("/users/admin", headers=auth(admin_token))
        assert self_delete.status_code == 400


def test_metrics_endpoint_exposes_prometheus_payload():
    app = create_app(udp_host="127.0.0.1", udp_port=0)

    with TestClient(app) as client:
        response = client.get("/metrics")

        assert response.status_code == 200
        assert "rescueradio_messages_published_total" in response.text
