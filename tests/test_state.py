import pytest
import asyncio

from app.repositories.messages import InMemoryMessageRepository


def valid_message(index: int) -> dict:
    return {
        "type": "SEND_MESSAGE",
        "usuario": "Lucas",
        "timestamp_iso": "2026-06-20T12:00:00Z",
        "corpo_texto": f"Mensagem {index}",
    }


@pytest.mark.anyio
async def test_in_memory_message_repository_keeps_last_50_messages():
    repository = InMemoryMessageRepository()

    for index in range(51):
        await repository.add_message("canal-geral", valid_message(index))

    briefing = await repository.get_briefing("canal-geral")

    assert len(briefing) == 50
    assert briefing[0]["corpo_texto"] == "Mensagem 1"
    assert briefing[-1]["corpo_texto"] == "Mensagem 50"


@pytest.mark.anyio
async def test_in_memory_message_repository_isolates_channels():
    repository = InMemoryMessageRepository()

    await repository.add_message("canal-alfa", valid_message(1))

    assert await repository.get_briefing("canal-geral") == []
    assert len(await repository.get_briefing("canal-alfa")) == 1


@pytest.mark.anyio
async def test_in_memory_message_repository_handles_concurrent_writes():
    repository = InMemoryMessageRepository(buffer_size=200)

    await asyncio.gather(
        *[
            repository.add_message("canal-geral", valid_message(index))
            for index in range(100)
        ]
    )

    briefing = await repository.get_briefing("canal-geral")

    assert len(briefing) == 100
