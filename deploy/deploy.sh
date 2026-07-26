#!/bin/bash
# abba-sheets-agent'ni VPS'ga o'rnatish/yangilash (Mac'dan ishga tushiriladi).
#
# Ishlatish:
#   ./deploy/deploy.sh root@SERVER_IP             # to'liq o'rnatish + sinovlar (idempotent)
#   ./deploy/deploy.sh root@SERVER_IP --code      # faqat kod sync + bot restart
#   ./deploy/deploy.sh root@SERVER_IP --enable    # SWITCHOVER: serverda yoqish + Mac'da o'chirish
#   ./deploy/deploy.sh root@SERVER_IP --rollback  # teskari: serverda o'chirish + Mac'da yoqish
#
# MUHIM: oddiy o'rnatish service'larni YOQMAYDI — Mac va server bir vaqtda
# ishlasa Telegram polling konflikti (409) va ikki nusxa hisobot bo'ladi.
# Sinovlar o'tgach --enable bilan almashtiriladi. Batafsil: deploy/MIGRATION.md
set -euo pipefail

SSH_DEST=${1:?"Ishlatish: deploy.sh root@SERVER_IP [--code|--enable|--rollback]"}
MODE=${2:-full}
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER=abba
APP_DIR=/home/$APP_USER/abba-sheets-agent
MAC_AGENT=com.abba.sheets-agent
MAC_BOT=com.abba.sheets-bot

say() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

# ---------- switchover / rollback ----------
if [ "$MODE" = "--enable" ]; then
  say "SWITCHOVER: server yoqilmoqda"
  ssh "$SSH_DEST" "systemctl daemon-reload && systemctl enable --now abba-sheets-bot.service abba-sheets-agent.timer && systemctl status abba-sheets-bot --no-pager -l | head -5"
  say "Mac'dagi launchd o'chirilmoqda"
  launchctl bootout "gui/$(id -u)/$MAC_AGENT" 2>/dev/null && echo "  $MAC_AGENT o'chdi" || echo "  $MAC_AGENT allaqachon o'chiq"
  launchctl bootout "gui/$(id -u)/$MAC_BOT" 2>/dev/null && echo "  $MAC_BOT o'chdi" || echo "  $MAC_BOT allaqachon o'chiq"
  echo
  echo "✅ Endi bot va kunlik 09:00 SERVER'da. Mac-sync o'rnatilganini tekshiring"
  echo "   (hisobotlar vault'ga tushishi uchun): deploy/mac-sync/install.sh"
  exit 0
fi
if [ "$MODE" = "--rollback" ]; then
  say "ROLLBACK: serverda o'chirilmoqda"
  ssh "$SSH_DEST" "systemctl disable --now abba-sheets-bot.service abba-sheets-agent.timer" || true
  say "Mac'dagi launchd qayta yoqilmoqda"
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$MAC_AGENT.plist" 2>/dev/null || echo "  $MAC_AGENT allaqachon yoqiq"
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$MAC_BOT.plist" 2>/dev/null || echo "  $MAC_BOT allaqachon yoqiq"
  echo "✅ Hammasi Mac'ga qaytdi."
  exit 0
fi

# ---------- 1. server bazasi (faqat full) ----------
if [ "$MODE" != "--code" ]; then
  say "1/6 Server bazasi: paketlar, chromium, TZ, user, firewall"
  ssh "$SSH_DEST" bash -s <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git rsync curl ufw \
  ca-certificates fonts-liberation fonts-noto-color-emoji >/dev/null
# Chromium: Debian'da apt'dan; Ubuntu snap-transitional yiqilsa Google Chrome .deb
if ! command -v chromium >/dev/null 2>&1 && ! command -v chromium-browser >/dev/null 2>&1 \
   && ! command -v google-chrome-stable >/dev/null 2>&1; then
  apt-get install -y -qq chromium >/dev/null 2>&1 \
    || apt-get install -y -qq chromium-browser >/dev/null 2>&1 \
    || {
      echo "  chromium apt'dan chiqmadi — Google Chrome .deb o'rnatilmoqda"
      curl -fsSL -o /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
      apt-get install -y -qq /tmp/chrome.deb >/dev/null
      rm -f /tmp/chrome.deb
    }
fi
timedatectl set-timezone Asia/Tashkent || true
id abba >/dev/null 2>&1 || useradd -m -s /bin/bash abba
# Firewall: kirish faqat SSH, chiqish ochiq
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow OpenSSH >/dev/null
ufw --force enable >/dev/null
echo "  server bazasi OK ($(. /etc/os-release && echo "$PRETTY_NAME"), TZ=$(timedatectl show -p Timezone --value))"
REMOTE
fi

# ---------- 2. kod sync ----------
say "2/6 Kod sync (rsync)"
ssh "$SSH_DEST" "mkdir -p $APP_DIR"
rsync -az --delete \
  --exclude venv/ --exclude .git/ --exclude __pycache__/ --exclude '*.pyc' \
  --exclude .DS_Store --exclude data/ --exclude .env --exclude .env.server \
  --exclude credentials/ \
  "$LOCAL_DIR/" "$SSH_DEST:$APP_DIR/"

if [ "$MODE" != "--code" ]; then
  # data: bor tarix bilan birinchi ko'chirish; serverdagi yangiroq fayllar bosilmaydi
  say "3/6 Data + credentials + .env ko'chirish"
  rsync -az --ignore-existing --exclude 'logs/' --exclude 'qa-pdf/' \
    "$LOCAL_DIR/data/" "$SSH_DEST:$APP_DIR/data/"
  rsync -az "$LOCAL_DIR/credentials/" "$SSH_DEST:$APP_DIR/credentials/"
  # .env.server bo'lsa u yuboriladi (masalan ANTHROPIC_API_KEY faqat serverda);
  # aks holda Mac .env (CLAUDE_CODE_OAUTH_TOKEN bilan) ishlatiladi
  if [ -f "$LOCAL_DIR/.env.server" ]; then
    rsync -az "$LOCAL_DIR/.env.server" "$SSH_DEST:$APP_DIR/.env"
    echo "  .env.server → server .env"
  else
    rsync -az "$LOCAL_DIR/.env" "$SSH_DEST:$APP_DIR/.env"
    echo "  Mac .env → server .env"
  fi

  # ---------- 4. huquqlar, venv, claude CLI ----------
  say "4/6 Huquqlar (600), venv, claude CLI"
  ssh "$SSH_DEST" bash -s <<REMOTE
set -euo pipefail
chown -R $APP_USER:$APP_USER $APP_DIR
chmod 600 $APP_DIR/.env
chmod 700 $APP_DIR/credentials
chmod 600 $APP_DIR/credentials/* 2>/dev/null || true
sudo -u $APP_USER bash -c '
  set -euo pipefail
  cd $APP_DIR
  [ -x venv/bin/python ] || python3 -m venv venv
  venv/bin/pip install -q --upgrade pip
  venv/bin/pip install -q -r requirements.txt
  export PATH="\$HOME/.claude/local:\$HOME/.local/bin:/usr/local/bin:\$PATH"
  if ! command -v claude >/dev/null 2>&1; then
    echo "  claude CLI o'\''rnatilmoqda (native installer)..."
    curl -fsSL https://claude.ai/install.sh | bash >/dev/null
  fi
  command -v claude >/dev/null 2>&1 || { echo "XATO: claude CLI o'\''rnatilmadi"; exit 1; }
  echo "  venv + claude CLI OK (\$(claude --version 2>/dev/null | head -1))"
'
# auth borligini tekshirish (claude uchun)
if ! grep -qE '^(CLAUDE_CODE_OAUTH_TOKEN|ANTHROPIC_API_KEY)=' $APP_DIR/.env; then
  echo "  ⚠️ OGOHLANTIRISH: .env'da CLAUDE_CODE_OAUTH_TOKEN ham ANTHROPIC_API_KEY ham yo'q —"
  echo "     Mac'da 'claude setup-token' qilib tokenni .env'ga qo'shing, keyin qayta deploy."
fi
REMOTE

  # ---------- 5. systemd unit'lar (enable EMAS) ----------
  say "5/6 systemd unit'lar o'rnatilmoqda (hali YOQILMAYDI)"
  rsync -az "$LOCAL_DIR/deploy/systemd/" "$SSH_DEST:/etc/systemd/system/"
  ssh "$SSH_DEST" "systemctl daemon-reload && echo '  unit fayllar joyida (yoqish: deploy.sh --enable)'"

  # ---------- 6. sinovlar ----------
  say "6/6 Sinovlar: Sheets → Chrome → claude → dashboard → Telegram salom"
  RC=0
  ssh "$SSH_DEST" sudo -u $APP_USER bash -s <<'REMOTE' || RC=$?
set -uo pipefail
cd "$HOME/abba-sheets-agent"
export PATH="$HOME/.claude/local:$HOME/.local/bin:/usr/local/bin:$PATH"
export PYTHONWARNINGS="ignore"
set -a; . ./.env; set +a
FAIL=0

echo "  [1/5] Google Sheets o'qish..."
venv/bin/python - <<'PY' || FAIL=1
import fetch
gc = fetch.gclient()
cfg = fetch.load_config()
sh, tabs = fetch.list_tabs(gc, cfg[0]["id"])
print(f"      OK: {cfg[0]['name']} — {len(tabs)} tab ko'rindi")
PY

echo "  [2/5] Chrome headless PDF..."
chrome_test() {
  venv/bin/python - <<'PY'
import render_pdf
render_pdf.render_qa(
    {"title": "Server sinovi", "summary": "Chrome headless PDF render ishlayapti.",
     "question": "deploy-test", "source": "deploy.sh"},
    "/tmp/deploy-test.pdf")
print("      OK: /tmp/deploy-test.pdf")
PY
}
if ! chrome_test; then
  if ! grep -q '^CHROME_FLAGS=' .env; then
    echo '      birinchi urinish yiqildi — CHROME_FLAGS="--no-sandbox" bilan qayta...'
    printf '\nCHROME_FLAGS=--no-sandbox\n' >> .env
    set -a; . ./.env; set +a
    chrome_test || FAIL=1
  else
    FAIL=1
  fi
fi

echo "  [3/5] claude -p ping..."
venv/bin/python - <<'PY' || FAIL=1
import analyze
analyze.load_env()
ans = analyze.run_claude("Javob sifatida faqat OK deb yoz.", effort="low")
print(f"      OK: claude javob berdi ({ans[:20]!r})")
PY

echo "  [4/5] Dashboard yozuv (allowlist writer)..."
LASTJ=$(ls -1d data/snapshots/*/ 2>/dev/null | sort | tail -20 | while read -r d; do
  [ -f "$d/report.json" ] && echo "${d%/}"; done | tail -1 | xargs -I{} basename {})
if [ -n "$LASTJ" ]; then
  venv/bin/python dashboard.py --date "$LASTJ" \
    && echo "      OK: dashboard yangilandi ($LASTJ ma'lumoti bilan)" \
    || { echo "      ⚠️ dashboard yozuvi yiqildi (SA Editor'ligini tekshiring)"; FAIL=1; }
else
  echo "      o'tkazildi: report.json'li snapshot yo'q"
fi

echo "  [5/5] Telegram salom..."
if [ "$FAIL" = "0" ]; then
  venv/bin/python send.py --text "🖥 Server'dan salom! abba-sheets-agent VPS'ga o'rnatildi, barcha sinovlar o'tdi: Sheets ✅ Chrome-PDF ✅ claude ✅ Dashboard ✅
Yoqish uchun (Mac'dan): ./deploy/deploy.sh <server> --enable" || FAIL=1
else
  venv/bin/python send.py --text "⚠️ Server o'rnatildi, lekin ba'zi sinovlar yiqildi — deploy log'iga qarang. --enable QILMANG hali." || true
fi
exit $FAIL
REMOTE
  echo
  if [ "$RC" = "0" ]; then
    echo "✅ O'rnatish tugadi, sinovlar o'tdi. Keyingi qadam (almashtirish):"
    echo "   ./deploy/deploy.sh $SSH_DEST --enable"
  else
    echo "❌ Sinovlarda xato bor — yuqoridagi log'ga qarang. Service'lar yoqilmagan, Mac ishlashda davom etadi."
    exit 1
  fi
else
  # --code rejimi: bot ishlab turgan bo'lsa yangi kod bilan restart
  ssh "$SSH_DEST" "chown -R $APP_USER:$APP_USER $APP_DIR; systemctl try-restart abba-sheets-bot.service 2>/dev/null && echo '  bot yangi kod bilan restart' || echo '  bot ishlamayapti (restart shart emas)'"
  echo "✅ Kod sync tugadi."
fi
