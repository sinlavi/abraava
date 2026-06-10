#!/bin/bash

# Function to setup wgcf
setup_wgcf() {
    if [ ! -f "wgcf-profile.conf" ]; then
        echo "🔧 Registering wgcf..."
        yes | wgcf register
        wgcf generate
    fi
}

# Function to setup wireproxy config
setup_wireproxy() {
    echo "🔧 Creating wireproxy config..."
    cat > wireproxy.conf <<EOF
[WG]
PrivateKey = $(grep PrivateKey wgcf-profile.conf | cut -d " " -f 3)
Address = $(grep Address wgcf-profile.conf | cut -d " " -f 3)
PublicKey = $(grep PublicKey wgcf-profile.conf | cut -d " " -f 3)
Endpoint = $(grep Endpoint wgcf-profile.conf | cut -d " " -f 3)

[Socks5]
BindAddress = 127.0.0.1:1080
EOF
}

# Register and setup WARP if config doesn't exist
setup_wgcf
setup_wireproxy

# Start wireproxy in background
echo "🚀 Starting wireproxy..."
wireproxy -c wireproxy.conf &

# Wait for wireproxy to be ready
echo "⏳ Waiting for wireproxy..."
for i in {1..30}; do
    if curl -s -x socks5h://127.0.0.1:1080 https://cloudflare.com/cdn-cgi/trace | grep -q "warp=on"; then
        echo "✅ WARP is ready!"
        break
    fi
    echo "⏳ Attempt $i/30: WARP not ready yet..."
    sleep 2
done

# Set proxy environment variables
export HTTP_PROXY="socks5h://127.0.0.1:1080"
export HTTPS_PROXY="socks5h://127.0.0.1:1080"
export ALL_PROXY="socks5h://127.0.0.1:1080"

# Start the bot
echo "🚀 Starting ABRAAVA bot..."
exec python main.py
