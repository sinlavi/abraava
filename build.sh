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

# Download warp-plus
if [ ! -f "warp-plus" ]; then
    echo "Downloading warp-plus..."
    curl -L https://github.com/bepass-org/warp-plus/releases/download/v1.2.6/warp-plus_linux-amd64.zip -o warp-plus.zip
    unzip warp-plus.zip
    chmod +x warp-plus
    rm warp-plus.zip
fi

echo "Build completed successfully."
