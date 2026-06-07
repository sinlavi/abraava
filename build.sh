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

echo "Build completed successfully."
