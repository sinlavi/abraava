#!/bin/bash

# Ensure dbus is running (required for warp-svc)
service dbus start || true

# Start WARP service in the background
warp-svc &

# Wait for warp-svc to start
sleep 5

# Register and configure WARP
echo "🔧 Configuring WARP..."
warp-cli --accept-tos register || true
warp-cli --accept-tos set-mode proxy
warp-cli --accept-tos connect

echo "⏳ Waiting for WARP to connect..."
for i in {1..30}; do
    if curl -x socks5h://127.0.0.1:1080 -s https://www.cloudflare.com/cdn-cgi/trace | grep -q "warp=on"; then
        echo "✅ WARP is connected!"
        break
    fi
    echo "⏳ Attempt $i/30..."
    sleep 2
done

# Show external IP via WARP
curl -x socks5h://127.0.0.1:1080 -s https://www.cloudflare.com/cdn-cgi/trace | grep "ip=" || echo "⚠️ Could not get IP via WARP"

# Start the bot
echo "🚀 Starting ABRAAVA bot..."
python main.py
