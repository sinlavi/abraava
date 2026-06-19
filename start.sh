#!/bin/bash

# Start D-Bus if needed (sometimes helps with warp-svc)
mkdir -p /run/dbus
dbus-daemon --system --fork --readonly

# Start the WARP service
warp-svc &

# Wait for warp-svc socket to be ready
echo "Waiting for warp-svc to start..."
for i in {1..30}; do
    if [ -S /run/cloudflare-warp/warp_service.sock ]; then
        echo "warp-svc is ready."
        break
    fi
    sleep 1
done

# Register WARP (ignore if already registered)
warp-cli --accept-tos registration new || true

# Set WARP to proxy mode
warp-cli --accept-tos mode proxy

# Set Proxy port explicitly just in case
warp-cli --accept-tos proxy port 1080

# Connect to WARP
warp-cli --accept-tos connect

# Wait for WARP to connect
echo "Waiting for WARP to connect..."
for i in {1..30}; do
    if warp-cli --accept-tos status | grep -q "Connected"; then
        echo "WARP is connected."
        break
    fi
    warp-cli --accept-tos status
    sleep 2
done

# Verify connection via proxy
echo "Verifying connection through proxy..."
curl --socks5-hostname 127.0.0.1:1080 -I https://www.google.com

# Start the bot
python main.py
