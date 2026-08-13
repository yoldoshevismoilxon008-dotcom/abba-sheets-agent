#!/bin/bash
# Hisobotlar repo'sidan vault'ga pull (Mac, har 10 daqiqa — com.abba.reports-pull).
# hisobotlar/ → ~/claude-brain/abba-sheets-agent/hisobotlar/ ; chat/ → ~/claude-brain/chat/ (B2.2)
# O'rnatish: ./install.sh git@github.com:USER/abba-hisobotlar.git
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$DIR/../.." && pwd)"

[ -f "$DIR/repo.conf" ] || { echo "repo.conf yo'q — avval install.sh"; exit 0; }
. "$DIR/repo.conf"

CLONE="$HOME/.abba-hisobotlar"
VAULT="$HOME/claude-brain/abba-sheets-agent/hisobotlar"
LOG="$APP/data/logs/reports-pull.log"
mkdir -p "$APP/data/logs"
exec >>"$LOG" 2>&1
echo "--- pull $(date '+%F %T') ---"

if [ ! -d "$CLONE/.git" ]; then
  git clone -q "$REPORTS_REPO_URL" "$CLONE" || { echo "clone bo'lmadi"; exit 0; }
else
  git -C "$CLONE" pull -q --rebase || { echo "pull bo'lmadi (tarmoq?)"; exit 0; }
fi

mkdir -p "$VAULT"
rsync -a --update "$CLONE/hisobotlar/" "$VAULT/" 2>/dev/null || true
/usr/bin/python3 "$DIR/vault_index.py" || echo "INDEX yangilash yiqildi"

# B2.2: chat arxivi → vault ILDIZIGA (~/claude-brain/chat/), hisobotlar ichida EMAS.
# vault_sync bu yo'llarni source="chat" deb ingest qiladi (brain-push orqali bilim repo'siga).
CHATVAULT="$HOME/claude-brain/chat"
mkdir -p "$CHATVAULT"
rsync -a --update "$CLONE/chat/" "$CHATVAULT/" 2>/dev/null || true
echo "pull OK"
