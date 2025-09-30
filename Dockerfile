FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps: Chrome + ffmpeg + libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates fonts-liberation \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libdrm2 libgbm1 libgtk-3-0 \
    libnspr4 libnss3 libu2f-udev libvulkan1 libx11-6 libx11-xcb1 libxcb1 \
    libxcomposite1 libxcursor1 libxdamage1 libxext6 libxfixes3 libxkbcommon0 \
    libxrandr2 libxshmfence1 libxss1 libxtst6 xdg-utils ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Google Chrome
RUN set -eux; \
    wget -nv -O /usr/share/keyrings/google-linux-keyring.gpg https://dl.google.com/linux/linux_signing_key.pub && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-linux-keyring.gpg] https://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && apt-get install -y --no-install-recommends google-chrome-stable && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user with home directory
RUN groupadd -r appuser && \
    useradd -r -g appuser -u 1000 -m -d /home/appuser appuser && \
    mkdir -p /home/appuser/.cache && \
    chown -R appuser:appuser /home/appuser

WORKDIR /app

# Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App
COPY . .

# Create download mount point and set permissions
RUN mkdir -p /downloads && \
    chown -R appuser:appuser /app /downloads

# Default environment (can be overridden)
ENV DOWNLOAD_DIR=/downloads \
    QUALITY=480p30 \
    POLL_SECONDS=60 \
    LIVE_CHECK_SECONDS=60 \
    HOME=/home/appuser

# Run as non-root user
USER appuser

CMD ["python", "auto_runner.py"]
