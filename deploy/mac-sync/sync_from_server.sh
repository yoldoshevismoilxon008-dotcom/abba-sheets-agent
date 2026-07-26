#!/bin/bash
# Server'dan yangi hisobotlarni tortib Obsidian vault'ga eksport qiladi.
# Mac'da soatiga 1 marta launchd (com.abba.sheets-sync) ishga tushiradi.
# O'rnatish: ./install.sh root@SERVER_IP
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$DIR/../.." && pwd)"

[ -f "$DIR/server.conf" ] || { echo "server.conf yo'q — avval install.sh"; exit 0; }
. "$DIR/server.conf"

LOG="$APP/data/logs/sync.log"
mkdir -p "$APP/data/logs"
exec >>"$LOG" 2>&1
echo "--- sync $(date '+%F %T') ($SSH_DEST) ---"

# Server javob bermasa jim chiqamiz — keyingi soatda yana uriniladi
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$SSH_DEST" true 2>/dev/null; then
  echo "server ulanmadi — o'tkazib yuborildi"
  exit 0
fi

# Faqat hisobot fayllari (snapshot json'lar emas — ular katta va shart emas)
rsync -azm --update \
  --include='*/' --include='report.md' --include='report.pdf' --include='audit.md' \
  --exclude='*' \
  "$SSH_DEST:/home/abba/abba-sheets-agent/data/snapshots/" "$APP/data/snapshots/" \
  || { echo "rsync xatosi"; exit 0; }

# Oxirgi 3 kunni vault'ga eksport (idempotent — takror link qo'shilmaydi)
for i in 0 1 2; do
  D=$(date -v-"$i"d +%F 2>/dev/null || date -d "$i days ago" +%F)
  if [ -f "$APP/data/snapshots/$D/report.md" ]; then
    "$APP/venv/bin/python" "$APP/export_obsidian.py" --date "$D"
  fi
done
echo "sync OK"
