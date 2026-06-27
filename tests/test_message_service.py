import pytest

from app.message_service import MessageService
from app.pubsub import InMemoryPubSubService
from app.state import InMemoryMessageRepository
from app.websocket_manager import WebSocketConnectionManager


class FailingAuditPublisher:
    async def start(self):
        return None

    async def publish(self, event_type: str, payload: dict):
        raise RuntimeError("kafka unavailable")

    async def stop(self):
        return None


def valid_message() -> dict:
    return {
        "type": "SEND_MESSAGE",
        "usuario": "Lucas",
        "timestamp_iso": "2026-06-09T12:00:00Z",
        "corpo_texto": "Equipe Alfa chegou ao local.",
    }


@pytest.mark.anyio
async def test_audit_failure_does_not_rollback_message_publication():
    repository = InMemoryMessageRepository()
    pubsub = InMemoryPubSubService(WebSocketConnectionManager())
    service = MessageService(repository, pubsub, FailingAuditPublisher())

    is_valid, result = await service.publish("canal-geral", valid_message())

    assert is_valid is True
    assert result["usuario"] == "Lucas"
    assert await repository.get_briefing("canal-geral") == [valid_message()]
