# syntax=docker/dockerfile:1
FROM python:3.11-slim

# ── System deps (Chromium for patchright + Node.js for WASM sign) ─────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget gnupg ca-certificates \
    # Chromium system libs
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libdbus-1-3 libxkbcommon0 libx11-6 libxcomposite1 \
    libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libxshmfence1 libgles2 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js 20 ────────────────────────────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── App ───────────────────────────────────────────────────────────────────────
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install patchright's patched Chromium
RUN python -m patchright install chromium --with-deps

COPY . .

# Pre-download WASM so first run is faster
RUN python -c "from solver.sign import _ensure_files; _ensure_files()" || true

ENV PYTHONUNBUFFERED=1 \
    COUNT=1 \
    THREADS=1 \
    HEADLESS=true \
    OUTPUT_FILE=/app/accounts.txt \
    LOG_LEVEL=INFO

CMD ["python", "main.py"]
