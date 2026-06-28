from fastapi import APIRouter, Depends

from app.dependencies import (
    get_audit_publisher,
    get_current_user,
    get_message_repository,
    get_pubsub_service,
    require_role,
)

router = APIRouter(prefix="/channels", tags=["Chat"])


@router.delete("/{channel_id}/messages")
async def clear_channel_messages(
    channel_id: str,
    current_user: dict = Depends(get_current_user),
    message_repository=Depends(get_message_repository),
    pubsub_service=Depends(get_pubsub_service),
    audit_publisher=Depends(get_audit_publisher),
):
    require_role(current_user, {"admin"})
    removed = await message_repository.clear_channel(channel_id)
    await pubsub_service.publish_message(
        channel_id,
        {
            "type": "CHAT_CLEARED",
            "channel_id": channel_id,
            "cleared_by": current_user["username"],
            "removed": removed,
        },
    )
    await audit_publisher.publish(
        "chat_cleared",
        {
            "channel_id": channel_id,
            "removed": removed,
            "cleared_by": current_user["username"],
        },
    )
    return {"channel_id": channel_id, "removed": removed}
