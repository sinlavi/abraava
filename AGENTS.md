# Developer Guidelines for ABRAAVA

Welcome to the ABRAAVA development! This bot is designed with cross-platform compatibility and high performance in mind.

## Core Principles

- **Multi-platform Abstraction:** Never use `balethon` or `telethon` directly in handlers or services. Always use the `BotClient`, `WrappedMessage`, and `WrappedCallbackQuery` from `core/bot_client.py`.
- **Informative UI:** Maintain a consistent UI using emojis (🎤 for artist, 💿 for album, 🎵 for track). Use RTL-friendly formatting (emojis at the end for Persian text).
- **Metadata First:** Always prioritize metadata. Ensure every downloaded track is properly tagged with ID3 tags using `TaggingService`.
- **Caching:** Use the central 3rah API (`index.php`) as the primary cache for metadata and mirrors. Use local SQLite for transient data like lyrics.
- **Asynchronous Everything:** All network and I/O operations must be asynchronous. Use `loop.run_in_executor` for blocking operations (like `mutagen` or `yt_dlp` sync calls).

## Project Structure

- `bot/handlers/`: Contains event handlers. Logic should be minimal here; delegate to services.
- `services/`: The "brain" of the bot. Put all reusable business logic here.
- `utils/`: Small, stateless helper functions.
- `core/`: Initialization and configuration.
- `crawlers/`: External data retrieval.

## Coding Standards

- **Type Hinting:** Use type hints for all function arguments and return types.
- **Error Handling:** Always wrap network calls in `try...except` and log errors using the centralized `logger`.
- **Performance:** Use `asyncio.gather` for concurrent network requests where order doesn't matter.
- **Platform Awareness:** When adding platform-specific features, check `core.config.PLATFORM`.

## Key Abstractions

### `BotClient`
The unified entry point for all bot operations.
```python
# Sending a message
await bot.send_message(chat_id, "Hello", reply_markup=markup)

# Sending media
await bot.send_audio(chat_id, audio_bytes, caption="Music")
```

### `Button`
A platform-agnostic button class.
```python
Button(text="Click me", callback_data="btn_clicked")
```

## Testing

Always run tests before submitting changes (once the test suite is established).
```bash
pytest tests/
```
