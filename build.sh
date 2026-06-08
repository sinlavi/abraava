#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install python dependencies
pip install --no-cache-dir -r requirements.txt

# Download static ffmpeg
if [ ! -f "ffmpeg" ]; then
    echo "Downloading static ffmpeg..."
    # Using John Van Sickle's reliable static builds
    curl -L https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz -o ffmpeg.tar.xz

    echo "Extracting ffmpeg..."
    mkdir -p ffmpeg_temp
    tar -xf ffmpeg.tar.xz -C ffmpeg_temp --strip-components=1

    mv ffmpeg_temp/ffmpeg .
    mv ffmpeg_temp/ffprobe .

    rm -rf ffmpeg_temp ffmpeg.tar.xz
    chmod +x ffmpeg ffprobe
    echo "FFmpeg installed successfully."
fi

# Download warp-plus
if [ ! -f "warp-plus" ]; then
    echo "Downloading warp-plus..."
    curl -L https://github.com/bepass-org/warp-plus/releases/download/v1.2.6/warp-plus_linux-amd64.zip -o warp-plus.zip
    python -m zipfile -e warp-plus.zip .
    chmod +x warp-plus
    rm warp-plus.zip
    echo "WARP installed successfully."
fi

echo "Build completed successfully."
