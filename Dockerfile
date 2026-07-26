# abba-sheets-agent — Railway image (bitta service: bot + 09:00 scheduler)
FROM python:3.12-slim-bookworm

# chromium (PDF render) + fontlar (o'zbekcha matn + emoji) + git (hisobot push)
# + nodejs/npm (claude CLI) — bitta qatlamda, keshni tozalab
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium fonts-liberation fonts-noto-color-emoji \
      git nodejs npm ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @anthropic-ai/claude-code \
    && npm cache clean --force

WORKDIR /app

# Avval deps — kod o'zgarganda qatlam keshi saqlansin
COPY requirements.txt .
RUN python -m venv venv && venv/bin/pip install --no-cache-dir -r requirements.txt

COPY . .

# Konteyner uchun majburiy: --no-sandbox (root), --disable-dev-shm-usage (/dev/shm kichik)
ENV DATA_DIR=/data \
    CHROME_BIN=/usr/bin/chromium \
    CHROME_FLAGS="--no-sandbox --disable-dev-shm-usage" \
    PYTHONUNBUFFERED=1 \
    PYTHONWARNINGS=ignore \
    TZ=Asia/Tashkent

CMD ["venv/bin/python", "supervisor.py"]
