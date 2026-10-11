# abba-sheets-agent — Railway image (bitta service: bot + 09:00 scheduler)

# --- whisper.cpp build stage (STT: o'zbekcha rubaistt modeli uchun CLI) ---
FROM python:3.12-slim-bookworm AS whisper-build
RUN apt-get update && apt-get install -y --no-install-recommends \
      g++ cmake make git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# Versiya QOTIRILGAN (audit P2): ilgari HEAD olinardi — har build boshqa (tekshirilmagan)
# kod. Yangilash: tag va uning commit SHA'sini birga o'zgartiring (SHA tekshiriladi).
ARG WHISPER_CPP_REF=v1.9.4
ARG WHISPER_CPP_SHA=927cfce34f31707e17f2bff35c349632fb9e2c3a
# GGML_NATIVE=OFF — portable CPU build; BUILD_SHARED_LIBS=OFF — bitta statik binary
RUN git clone --depth 1 --branch "$WHISPER_CPP_REF" https://github.com/ggml-org/whisper.cpp /w \
    && test "$(git -C /w rev-parse HEAD)" = "$WHISPER_CPP_SHA" \
    && cmake -B /w/build -S /w -DCMAKE_BUILD_TYPE=Release \
         -DBUILD_SHARED_LIBS=OFF -DGGML_NATIVE=OFF \
         -DWHISPER_BUILD_TESTS=OFF \
    && cmake --build /w/build -j --target whisper-cli \
    && strip /w/build/bin/whisper-cli

# --- asosiy image ---
FROM python:3.12-slim-bookworm

# claude CLI versiyasi QOTIRILGAN (audit P2; npm «stable» kanali) — ilgari versiyasiz
# o'rnatilardi. Yangilash: shu ARG'ni ataylab oshiring.
ARG CLAUDE_CODE_VERSION=2.1.287
# chromium (PDF render) + fontlar (o'zbekcha matn + emoji) + git (hisobot push)
# + nodejs/npm (claude CLI) + ffmpeg (ovoz: OGG->WAV, TTS->Opus)
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium fonts-liberation fonts-noto-color-emoji \
      git nodejs npm ca-certificates curl ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && npm cache clean --force

COPY --from=whisper-build /w/build/bin/whisper-cli /usr/local/bin/whisper-cli

WORKDIR /app

# Avval deps — kod o'zgarganda qatlam keshi saqlansin
COPY requirements.txt .
RUN python -m venv venv && venv/bin/pip install --no-cache-dir -r requirements.txt

COPY . .

# Konteyner uchun majburiy: --no-sandbox (root), --disable-dev-shm-usage (/dev/shm kichik)
ENV DATA_DIR=/data \
    CHROME_BIN=/usr/bin/chromium \
    CHROME_FLAGS="--no-sandbox --disable-dev-shm-usage" \
    WHISPER_BIN=/usr/local/bin/whisper-cli \
    PYTHONUNBUFFERED=1 \
    PYTHONWARNINGS=ignore \
    TZ=Asia/Tashkent

CMD ["venv/bin/python", "supervisor.py"]
