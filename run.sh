#!/bin/bash
# abba-sheets-agent kunlik pipeline: fetch → diff → analyze → send.
# Har qadam xatosida Telegram'ga alert ketadi, hamma chiqish data/logs/ ga yoziladi.
set -uo pipefail
cd "$(dirname "$0")"

# launchd muhitida PATH minimal bo'ladi — claude va boshqalar uchun to'ldiramiz
export PATH="$HOME/.claude/local:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
# Python 3.9 EOL / LibreSSL deprecation warninglari logni iflos qilmasin
export PYTHONWARNINGS="ignore"

TODAY=$(date +%F)
mkdir -p data/logs data/snapshots
LOG="data/logs/$TODAY.log"

# Terminaldan qo'lda ishga tushirilsa ekranga ham chiqsin, launchd'da faqat log'ga
if [ -t 1 ]; then
  exec > >(tee -a "$LOG") 2>&1
else
  exec >>"$LOG" 2>&1
fi

echo "===== abba-sheets-agent: $(date '+%F %T') ====="

if [ -f .env ]; then set -a; . ./.env; set +a; fi

if [ ! -x venv/bin/python ]; then
  echo "XATO: venv topilmadi. O'rnatish: python3 -m venv venv && venv/bin/pip install -r requirements.txt"
  exit 1
fi
PY=venv/bin/python

alert() {
  echo "XATO: $1"
  "$PY" send.py --text "⚠️ abba-sheets-agent ($TODAY): $1. Log: data/logs/$TODAY.log" \
    || echo "(xato alertning o'zi ham yuborilmadi — token/chat_id tekshiring)"
  exit 1
}

"$PY" fetch.py   --date "$TODAY" || alert "fetch bosqichi yiqildi"
"$PY" diff.py    --date "$TODAY" || alert "diff bosqichi yiqildi"
"$PY" analyze.py --date "$TODAY" || alert "analyze bosqichi yiqildi"

# Data audit: dushanba — to'liq bo'lim, boshqa kunlar — faqat kritik 1 qator
REPORT="data/snapshots/$TODAY/report.md"
if [ "$(date +%u)" = "1" ]; then
  if "$PY" audit.py --from-snapshot "$TODAY" --out "data/snapshots/$TODAY/audit.md"; then
    { echo ""; echo "———"; cat "data/snapshots/$TODAY/audit.md"; } >> "$REPORT"
  else
    echo "OGOHLANTIRISH: haftalik audit yiqildi — hisobot auditsiz ketadi"
  fi
else
  CRIT_LINE=$("$PY" audit.py --from-snapshot "$TODAY" --critical-line 2>/dev/null) || CRIT_LINE=""
  [ -n "$CRIT_LINE" ] && printf '\n%s\n' "$CRIT_LINE" >> "$REPORT"
fi

# Infografik PDF (yiqilsa — send.py avtomatik matn rejimida yuboradi)
PDF_ERR=0
"$PY" render_pdf.py --date "$TODAY" || PDF_ERR=1

SEND_ERR=0
"$PY" send.py    --date "$TODAY" || SEND_ERR=1

if [ "$PDF_ERR" = "1" ]; then
  echo "XATO: PDF render yiqildi — hisobot matn ko'rinishida ketdi"
  "$PY" send.py --text "⚠️ abba-sheets-agent ($TODAY): PDF render yiqildi, hisobot matn rejimida yuborildi. Log: data/logs/$TODAY.log" || true
fi

# Obsidian eksport — send yiqilsa ham hisobot vault arxiviga yozilsin.
# Serverda vault yo'q — Mac'dagi mac-sync skript hisobotlarni o'zi tortadi.
if [ -d "$HOME/claude-brain" ]; then
  if ! "$PY" export_obsidian.py --date "$TODAY"; then
    echo "XATO: Obsidian eksport yiqildi (hisobot data/snapshots/$TODAY/report.md da turibdi)"
    "$PY" send.py --text "⚠️ abba-sheets-agent ($TODAY): hisobot Obsidian vault'ga yozilmadi. Log: data/logs/$TODAY.log" || true
  fi
else
  echo "obsidian eksport: o'tkazib yuborildi (vault yo'q — server rejimi)"
fi

# Dashboard yangilash (dashboard_id to'ldirilgan bo'lsa) — yiqilsa alert, pipeline davom etadi
if grep -qE '^dashboard_id: *"[^"]+"' config.yaml; then
  if ! "$PY" dashboard.py --date "$TODAY"; then
    echo "XATO: dashboard yangilanmadi"
    "$PY" send.py --text "⚠️ abba-sheets-agent ($TODAY): dashboard yangilanmadi. Log: data/logs/$TODAY.log" || true
  fi
else
  echo "dashboard: o'tkazib yuborildi (dashboard_id yo'q)"
fi

[ "$SEND_ERR" = "1" ] && alert "send bosqichi yiqildi (hisobot data/snapshots/$TODAY/report.md da turibdi)"

# Retention: 30 kundan eski snapshot papkalarini o'chirish (papka nomi bo'yicha)
# date -v : BSD/macOS, date -d : GNU/Linux — ikkalasi ham qo'llanadi
CUTOFF=$(date -v-30d +%F 2>/dev/null || date -d "30 days ago" +%F)
for d in data/snapshots/*/; do
  [ -d "$d" ] || continue
  n=$(basename "$d")
  [[ "$n" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || continue
  if [[ "$n" < "$CUTOFF" ]]; then
    rm -rf "$d"
    echo "retention: $n o'chirildi (>30 kun)"
  fi
done

echo "===== tugadi: $(date '+%F %T') ====="
