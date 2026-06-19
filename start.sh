#!/bin/bash

# Start the WARP service
warp-svc &

# Wait for warp-svc to start
sleep 5

# Register WARP (ignore if already registered)
warp-cli --accept-tos registration new || true

# Set WARP to proxy mode
warp-cli --accept-tos mode proxy

# Connect to WARP
warp-cli --accept-tos connect

# Give WARP a moment to establish the connection
sleep 5

# Verify WARP status
warp-cli --accept-tos status

# Start the bot
python main.py
