import asyncio

from app.websocket_manager import WebSocketConnectionManager


class WorkingConnection:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


class BrokenConnection:
    async def send_json(self, message):
        raise RuntimeError("connection closed")


def test_broadcast_skips_sender_and_returns_recipient_count():
    manager = WebSocketConnectionManager()
    lucas = WorkingConnection()
    marcelo = WorkingConnection()
    manager.connections = {
        "canal-geral": {
            "Lucas": lucas,
            "Marcelo": marcelo,
        }
    }

    sent_count = asyncio.run(
        manager.broadcast(
            "canal-geral",
            {"type": "MESSAGE_RECEIVED"},
            exclude_usuario="Lucas",
        )
    )

    assert sent_count == 1
    assert lucas.messages == []
    assert marcelo.messages == [{"type": "MESSAGE_RECEIVED"}]


def test_broadcast_removes_broken_connections():
    manager = WebSocketConnectionManager()
    lucas = WorkingConnection()
    manager.connections = {
        "canal-geral": {
            "Lucas": lucas,
            "Marcelo": BrokenConnection(),
        }
    }

    sent_count = asyncio.run(
        manager.broadcast("canal-geral", {"type": "MEMBER_JOINED"})
    )

    assert sent_count == 1
    assert list(manager.connections["canal-geral"]) == ["Lucas"]
