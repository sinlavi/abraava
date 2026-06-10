#!/bin/bash

# Create bin directory
mkdir -p bin

# Download wgcf
if [ ! -f "bin/wgcf" ]; then
    echo "Downloading wgcf..."
    curl -L -o bin/wgcf https://github.com/ViRb3/wgcf/releases/download/v2.2.22/wgcf_2.2.22_linux_amd64
    chmod +x bin/wgcf
fi

# Download wireproxy
if [ ! -f "bin/wireproxy" ]; then
    echo "Downloading wireproxy..."
    curl -L -o wireproxy.tar.gz https://github.com/octeep/wireproxy/releases/download/v1.0.9/wireproxy_linux_amd64.tar.gz
    tar -xzf wireproxy.tar.gz
    mv wireproxy bin/
    rm wireproxy_linux_amd64.tar.gz wireproxy.tar.gz 2>/dev/null || true
    chmod +x bin/wireproxy
fi

# Install dependencies
pip install -r requirements.txt
