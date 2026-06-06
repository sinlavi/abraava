from typing import Dict

class LastMessageTracker:
    def __init__(self):
        self.last_messages: Dict[int, int] = {}

    def set_last(self, chat_id: int, message_id: int):
        self.last_messages[chat_id] = message_id

    def is_last(self, chat_id: int, message_id: int) -> bool:
        return self.last_messages.get(chat_id) == message_id

last_message_tracker = LastMessageTracker()
