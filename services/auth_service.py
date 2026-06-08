import json
import os
import asyncio
from pathlib import Path
from ytmusicapi import YTMusic
from core.logger import logger

class AuthService:
    OAUTH_PATH = "oauth.json"

    @classmethod
    def get_ytmusic_auth(cls):
        """Get auth data from file or environment variable."""
        # Check environment variable first (best for Render)
        env_auth = os.getenv("YTM_OAUTH_JSON")
        if env_auth:
            try:
                return json.loads(env_auth)
            except Exception as e:
                logger.error(f"Failed to parse YTM_OAUTH_JSON: {e}")

        # Fallback to local file
        if os.path.exists(cls.OAUTH_PATH):
            try:
                with open(cls.OAUTH_PATH, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to read {cls.OAUTH_PATH}: {e}")

        return None

    @classmethod
    async def run_setup_flow(cls):
        """Run the interactive setup flow in a separate thread."""
        if cls.get_ytmusic_auth():
            return

        def setup():
            try:
                print("\n" + "!"*60)
                print("ACTION REQUIRED: YouTube Music OAuth Setup")
                print("Visit the URL below and enter the code to authorize this bot.")
                print("!"*60 + "\n")

                # setup_oauth prints instructions and waits for user input
                headers = YTMusic.setup_oauth()

                with open(cls.OAUTH_PATH, "w") as f:
                    json.dump(headers, f, indent=4)

                print("\n" + "="*60)
                print("✅ SUCCESS: YouTube Music OAuth complete!")
                print(f"Credentials saved to {cls.OAUTH_PATH}")
                print("IMPORTANT for Render: Copy the contents of oauth.json to")
                print("an environment variable named 'YTM_OAUTH_JSON' for persistence.")
                print("="*60 + "\n")
            except Exception as e:
                logger.error(f"OAuth setup failed: {e}")

        await asyncio.get_event_loop().run_in_executor(None, setup)
