#!/bin/bash
set -x

# Ensure D-Bus directories exist
mkdir -p /var/run/dbus
mkdir -p /run/dbus

# Clean up old D-Bus sockets
rm -f /var/run/dbus/system_bus_socket
rm -f /run/dbus/system_bus_socket

# Generate D-Bus machine ID
dbus-uuidgen > /var/lib/dbus/machine-id

# Start D-Bus daemon
# The --system flag usually looks for /var/run/dbus/system_bus_socket
dbus-daemon --system --fork

# Wait for D-Bus socket to appear and ensure symlink compatibility
for i in {1..10}; do
    if [ -S /var/run/dbus/system_bus_socket ]; then
        echo "D-Bus socket found at /var/run/dbus/system_bus_socket"
        ln -sf /var/run/dbus/system_bus_socket /run/dbus/system_bus_socket
        break
    fi
    sleep 1
done

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

# Final check of settings
warp-cli --accept-tos settings

# Verify connection via proxy
echo "Verifying connection through proxy..."
for i in {1..10}; do
    if curl --socks5-hostname 127.0.0.1:1080 -I https://www.google.com; then
        echo "Proxy connectivity verified."
        break
    fi
    echo "Proxy not ready yet (or connection failed), retrying..."
    sleep 5
done

# Start the bot
echo "Starting the bot..."
python main.py
