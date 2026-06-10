#!/bin/bash

# Function to setup wgcf
setup_wgcf() {
    if [ ! -f "wgcf-profile.conf" ]; then
        echo "🔧 Registering wgcf..."
        # wgcf might need to write to its own config directory
        export WGCF_CONFIG_DIR="/tmp/wgcf"
        mkdir -p "$WGCF_CONFIG_DIR"
        yes | wgcf register
        wgcf generate
        cp "$WGCF_CONFIG_DIR/wgcf-profile.conf" .
    fi
}

# Function to setup wireproxy config
setup_wireproxy() {
    echo "🔧 Creating wireproxy config..."

    # Extract values from wgcf-profile.conf using sed
    PRIVATE_KEY=$(sed -n 's/^PrivateKey *= *//p' wgcf-profile.conf)
    ADDRESS=$(sed -n 's/^Address *= *//p' wgcf-profile.conf)
    PUBLIC_KEY=$(sed -n 's/^PublicKey *= *//p' wgcf-profile.conf)
    ENDPOINT=$(sed -n 's/^Endpoint *= *//p' wgcf-profile.conf)

    # Note: Address from wgcf often contains both IPv4 and IPv6 separated by comma.
    # Wireproxy might only support one or expects them in a specific way.
    # We'll take the first one (usually IPv4).
    FIRST_ADDRESS=$(echo $ADDRESS | cut -d',' -f1)

    cat > wireproxy.conf <<CONF
[WG]
PrivateKey = $PRIVATE_KEY
Address = $FIRST_ADDRESS
PublicKey = $PUBLIC_KEY
Endpoint = $ENDPOINT

[Socks5]
BindAddress = 127.0.0.1:1080
CONF
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
