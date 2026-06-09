from collections import deque


BUFFER_SIZE = 50


class ChannelState:
    def __init__(self):
        self.message_buffer: dict[str, deque[dict]] = {}

    def ensure_channel(self, channel_id: str):
        if channel_id not in self.message_buffer:
            self.message_buffer[channel_id] = deque(maxlen=BUFFER_SIZE)

    def add_message_to_buffer(self, channel_id: str, message: dict):
        self.ensure_channel(channel_id)
        self.message_buffer[channel_id].append(message)

    def get_briefing(self, channel_id: str) -> list[dict]:
        self.ensure_channel(channel_id)
        return list(self.message_buffer[channel_id])
