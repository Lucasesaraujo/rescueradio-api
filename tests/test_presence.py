import pytest

from app.presence import InMemoryPresenceService


@pytest.mark.anyio
async def test_in_memory_presence_tracks_members_by_channel():
    presence = InMemoryPresenceService()

    await presence.connect("canal-geral", "Lucas")
    await presence.connect("canal-geral", "Marcelo")
    await presence.connect("canal-alfa", "Julia")

    assert await presence.get_active_members("canal-geral") == [
        {"usuario": "Lucas", "status": "online"},
        {"usuario": "Marcelo", "status": "online"},
    ]
    assert await presence.get_active_members("canal-alfa") == [
        {"usuario": "Julia", "status": "online"}
    ]


@pytest.mark.anyio
async def test_in_memory_presence_removes_disconnected_member():
    presence = InMemoryPresenceService()

    await presence.connect("canal-geral", "Lucas")
    await presence.disconnect("canal-geral", "Lucas")

    assert await presence.get_active_members("canal-geral") == []
