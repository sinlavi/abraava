#!/bin/bash

# Function to setup wgcf
setup_wgcf() {
    if [ ! -f "wgcf-profile.conf" ]; then
        echo "🔧 Registering wgcf..."
        # Register and generate profile in the current app directory
        yes | wgcf register
        wgcf generate

        if [ ! -f "wgcf-profile.conf" ]; then
            echo "❌ Failed to generate wgcf-profile.conf"
            # Try to find where it might have been generated
            find . -name "wgcf-profile.conf"
        fi
    fi
}

# Function to setup wireproxy config
setup_wireproxy() {
    echo "🔧 Creating wireproxy config..."

    if [ -f "wgcf-profile.conf" ]; then
        # Extract values from wgcf-profile.conf using sed
        PRIVATE_KEY=$(sed -n 's/^PrivateKey *= *//p' wgcf-profile.conf)
        ADDRESS=$(sed -n 's/^Address *= *//p' wgcf-profile.conf)
        PUBLIC_KEY=$(sed -n 's/^PublicKey *= *//p' wgcf-profile.conf)
        ENDPOINT=$(sed -n 's/^Endpoint *= *//p' wgcf-profile.conf)

        # Note: Address from wgcf often contains both IPv4 and IPv6 separated by comma.
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
    else
        echo "❌ wgcf-profile.conf not found. Skip wireproxy setup."
    fi
}

# Register and setup WARP if config doesn't exist
setup_wgcf
setup_wireproxy

# Start wireproxy in background
if [ -f "wireproxy.conf" ]; then
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
else
    echo "⚠️ Wireproxy config missing. Running without proxy."
fi

# Start the bot
echo "🚀 Starting ABRAAVA bot..."
exec python main.py
