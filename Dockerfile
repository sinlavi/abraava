FROM python:3.11-slim-bookworm

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    lsb-release \
    ffmpeg \
    ca-certificates \
    dbus \
    && rm -rf /var/lib/apt/lists/*

# Install Cloudflare WARP
RUN curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] bookworm main" | tee /etc/apt/sources.list.d/cloudflare-warp.list \
    && apt-get update && apt-get install -y cloudflare-warp \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Copy and prepare the start script
COPY start.sh /start.sh
RUN chmod +x /start.sh

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PROXY=socks5h://127.0.0.1:1080
ENV HTTP_PROXY=socks5h://127.0.0.1:1080
ENV HTTPS_PROXY=socks5h://127.0.0.1:1080
ENV ALL_PROXY=socks5h://127.0.0.1:1080

CMD ["/start.sh"]
