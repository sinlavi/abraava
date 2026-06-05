import time
from typing import Dict, Optional, Tuple
from core.config import MESSAGE_OWNER_TTL

class MessageOwnerService:
    def __init__(self):
        self.message_owners: Dict[int, Tuple[int, float]] = {}

    def set_owner(self, message_id: int, owner_id: int):
        self.message_owners[message_id] = (owner_id, time.time())

    def get_owner(self, message_id: int) -> Optional[int]:
        data = self.message_owners.get(message_id)
        if data:
            owner_id, ts = data
            if time.time() - ts <= MESSAGE_OWNER_TTL:
                return owner_id
            else:
                self.message_owners.pop(message_id, None)
        return None

message_owner_service = MessageOwnerService()
