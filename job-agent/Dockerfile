FROM python:3.11-slim

# System dependencies: Chromium for Playwright, pandoc for PDF generation
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    pandoc \
    fonts-liberation \
    fonts-dejavu-core \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright's bundled Chromium (used when system Chromium unavailable)
RUN playwright install chromium --with-deps || true

COPY . .

# Runtime directories (mounted as volumes in production)
RUN mkdir -p logs outbox profile/variants db_data

ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/bin

CMD ["python", "main.py", "--schedule"]
