#!/bin/bash
set -x

# Setup D-Bus
mkdir -p /run/dbus
dbus-uuidgen > /var/lib/dbus/machine-id
dbus-daemon --system --fork --nopidfile

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

# Register WARP
echo "Registering WARP..."
warp-cli --accept-tos registration new || true

# Configure WARP
echo "Configuring WARP..."
warp-cli --accept-tos mode proxy
warp-cli --accept-tos proxy port 1080

# Connect to WARP
echo "Connecting to WARP..."
warp-cli --accept-tos connect

# Wait for WARP to connect
echo "Waiting for WARP connection status..."
for i in {1..30}; do
    STATUS=$(warp-cli --accept-tos status)
    echo "$STATUS"
    if echo "$STATUS" | grep -q "Connected"; then
        echo "WARP is connected."
        break
    fi
    sleep 2
done

# Verify connection via proxy
echo "Verifying connection through proxy..."
for i in {1..5}; do
    if curl --socks5-hostname 127.0.0.1:1080 -I https://www.google.com; then
        echo "Proxy connectivity verified."
        break
    fi
    echo "Proxy not ready yet, retrying..."
    sleep 5
done

# Start the bot
echo "Starting the bot..."
python main.py
