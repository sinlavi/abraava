#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install python dependencies
pip install --no-cache-dir -r requirements.txt

# Download static ffmpeg
if [ ! -f "ffmpeg" ]; then
    echo "Downloading static ffmpeg..."
    curl -L https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz -o ffmpeg.tar.xz
    tar -xf ffmpeg.tar.xz --wildcards '*/bin/ffmpeg' '*/bin/ffprobe'
    mv ffmpeg-master-latest-linux64-gpl/bin/ffmpeg .
    mv ffmpeg-master-latest-linux64-gpl/bin/ffprobe .
    rm -rf ffmpeg-master-latest-linux64-gpl ffmpeg.tar.xz
    chmod +x ffmpeg ffprobe
fi

# Download and Setup Cloudflare WARP (Alternative to caomingjun/warp for native environment)
if [ ! -f "warp-plus" ]; then
    echo "Downloading warp-plus..."
    # The user wants exactly like the old version. In the old version (GitHub Actions),
    # caomingjun/warp docker image was used. Since we are on Render's native environment,
    # we use warp-plus which is the CLI equivalent.
    curl -L https://github.com/bepass-org/warp-plus/releases/download/v1.2.6/warp-plus_linux-amd64.zip -o warp-plus.zip
    python -m zipfile -e warp-plus.zip .
    chmod +x warp-plus
    rm warp-plus.zip
fi

echo "Build completed successfully."
