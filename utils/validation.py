def is_valid_message(message) -> bool:
    if len(message.content or "") > 100:
        return False
    if hasattr(message, 'photo') and message.photo:
        return False
    if hasattr(message, 'video') and message.video:
        return False
    if hasattr(message, 'document') and message.document:
        return False
    if hasattr(message, 'audio') and message.audio:
        return False
    if hasattr(message, 'voice') and message.voice:
        return False
    return True
