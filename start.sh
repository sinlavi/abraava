#!/bin/bash

# Start WARP service in the background
warp-svc &

# Wait for warp-svc to start
sleep 2

# Register and configure WARP
warp-cli --accept-tos register
warp-cli --accept-tos set-mode proxy
warp-cli --accept-tos connect

echo "⏳ Waiting for WARP to connect..."
for i in {1..15}; do
    if curl -x socks5h://127.0.0.1:1080 -s https://www.cloudflare.com/cdn-cgi/trace | grep -q "warp=on"; then
        echo "✅ WARP is connected!"
        break
    fi
    echo "⏳ Attempt $i/15..."
    sleep 2
done

# Show external IP via WARP
curl -x socks5h://127.0.0.1:1080 -s https://www.cloudflare.com/cdn-cgi/trace | grep "ip="

# Start the bot
echo "🚀 Starting ABRAAVA bot..."
python main.py
