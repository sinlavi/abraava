# ABRAAVA Music Bot

ABRAAVA is a multi-platform music bot (supporting Bale and Telegram) designed for searching, previewing, and downloading music from various sources including iTunes, YouTube Music, SoundCloud, and Spotify.

## Features

- **Multi-platform support:** Unified codebase for both Bale and Telegram platforms.
- **Vast Music Library:** Search and download from iTunes (official), YouTube Music, SoundCloud, and Spotify.
- **Smart Downloads:**
  - Automatic quality adjustment to fit platform file size limits (e.g., 20MB for Bale).
  - High-quality MP3 downloads (up to 320kbps).
  - Full album downloads.
- **Rich Metadata:** Automatic ID3 tagging including title, artist, album, year, genre, and high-quality artwork.
- **Lyrics Support:** Fetching and tagging both plain and synchronized lyrics (LRC).
- **User Personalization:** Customizable settings for download quality, artwork display, quick search mode, and more.
- **Mini App Integration:** Web app support for enhanced user experience (on supported platforms).
- **Deep Linking:** Easily share tracks, albums, and artists via bot deep links.

## Architecture

The project is divided into several layers:
- **Bot Layer (`bot/`):** Handlers for commands, callbacks, and search results.
- **Core Layer (`core/`):** Centralized configuration, logging, and the `BotClient` abstraction for multi-platform support.
- **Service Layer (`services/`):** Business logic for downloads, lyrics, tagging, artwork processing, and API interaction.
- **Crawler Layer (`crawlers/`):** Adapters for external APIs (iTunes, YouTube).
- **Backend (`index.php`):** PHP-based API for central metadata caching and user management.

## Setup & Installation

### Prerequisites

- Python 3.11+
- FFmpeg (for audio processing)
- Cloudflare WARP (optional, for proxying)
- PHP environment (for the backend API)

### Environment Variables

Create a `.env` file in the root directory with the following variables:

```env
PLATFORM=bale # or 'telegram'
BOT_TOKEN=your_bot_token
TELEGRAM_API_ID=your_api_id # Required for Telegram
TELEGRAM_API_HASH=your_api_hash # Required for Telegram
API_BASE_URL=https://your-backend.com/index.php
API_TOKEN=your_api_token
SPOTIFY_CLIENT_ID=your_spotify_id
SPOTIFY_CLIENT_SECRET=your_spotify_secret
PROXY=socks5h://127.0.0.1:1080 # Optional
```

### Installation

1. Clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the bot:
   ```bash
   python main.py
   ```

## Development Guidelines

Refer to `AGENTS.md` for coding standards, architecture details, and contribution tips.

## License

This project is private. All rights reserved.
