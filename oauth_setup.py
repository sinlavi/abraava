import json
import os
import time
import requests
from ytmusicapi import YTMusic

def setup_ytmusic_oauth():
    oauth_path = "oauth.json"
    if os.path.exists(oauth_path):
        print(f"✅ {oauth_path} already exists.")
        return

    print("🔑 Initiating YTMusic OAuth setup...")
    try:
        # We'll use the internal methods of ytmusicapi to get the code without blocking the whole process indefinitely in a weird way
        # Actually, setup_oauth() is fine if we run it in a thread.
        # But we want to make sure the user sees it in Render logs.

        print("\n" + "="*50)
        print("IMPORTANT: YTMusic OAuth Setup")
        print("Please check the logs below for the login URL and code.")
        print("="*50 + "\n")

        # setup_oauth returns the session headers which we can save
        auth_data = YTMusic.setup_oauth()

        with open(oauth_path, "w") as f:
            json.dump(auth_data, f, indent=4)

        print(f"\n✅ OAuth setup complete! Saved to {oauth_path}")
        print("Note: On Render, this file is ephemeral. You should copy its contents to an environment variable for persistence.")

    except Exception as e:
        print(f"❌ OAuth setup failed: {e}")

if __name__ == "__main__":
    setup_ytmusic_oauth()
