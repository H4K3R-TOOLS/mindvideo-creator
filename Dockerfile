# syntax=docker/dockerfile:1
FROM python:3.11-slim

# ── Base tools & Xvfb virtual display ──────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget gnupg ca-certificates xvfb xauth \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js 20 ────────────────────────────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── Chromium system deps (exact list playwright/patchright needs on debian) ───
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    libxshmfence1 \
    fonts-liberation \
    fonts-noto-color-emoji \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps ───────────────────────────────────────────────────────────────
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install patchright Chromium binary
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN python -m patchright install chromium

# ── App source ────────────────────────────────────────────────────────────────
COPY . .

ENV PYTHONUNBUFFERED=1 \
    COUNT=1 \
    THREADS=1 \
    HEADLESS=false \
    DISPLAY=:99 \
    OUTPUT_FILE=/app/accounts.txt \
    LOG_LEVEL=INFO \
    PORT=8000

EXPOSE 8000

CMD ["xvfb-run", "-a", "-s", "-screen 0 1280x800x24", "python", "server.py"]
