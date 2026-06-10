FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    wget \
    xz-utils \
    procps \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install wgcf
RUN wget -O /usr/local/bin/wgcf https://github.com/ViRb3/wgcf/releases/download/v2.2.22/wgcf_2.2.22_linux_amd64 && \
    chmod +x /usr/local/bin/wgcf

# Install wireproxy
RUN wget https://github.com/octeep/wireproxy/releases/download/v1.0.9/wireproxy_linux_amd64.tar.gz && \
    tar -xzf wireproxy_linux_amd64.tar.gz && \
    mv wireproxy /usr/local/bin/ && \
    rm wireproxy_linux_amd64.tar.gz

# Set work directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Make start script executable
RUN chmod +x start.sh

# Start the application
CMD ["./start.sh"]
