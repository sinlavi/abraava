from typing import Dict, List

class LastMessageTracker:
    def __init__(self):
        self.recent_messages: Dict[int, List[int]] = {}

    def set_last(self, chat_id: int, message_id: int):
        if chat_id not in self.recent_messages:
            self.recent_messages[chat_id] = []

        # Add new message to the list
        self.recent_messages[chat_id].append(message_id)

        # Keep only the last 7 messages
        if len(self.recent_messages[chat_id]) > 7:
            self.recent_messages[chat_id].pop(0)

    def is_recent(self, chat_id: int, message_id: int) -> bool:
        return message_id in self.recent_messages.get(chat_id, [])

    def is_last(self, chat_id: int, message_id: int) -> bool:
        recent = self.recent_messages.get(chat_id, [])
        return recent[-1] == message_id if recent else False

last_message_tracker = LastMessageTracker()
