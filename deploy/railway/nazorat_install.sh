#!/bin/bash
# Railway hisobot nazorati (Mac launchd) — o'rnatish, yangilash yoki o'chirish.
#   bash deploy/railway/nazorat_install.sh           # o'rnatish; qayta ishga tushirilsa — yangilash
#   bash deploy/railway/nazorat_install.sh --ochir   # launchd'ni o'chirish (holat va log qoladi)
#
# hisobot_nazorat.py ~/.abba-nazorat/ ga NUSXA qilinadi. launchd ~/abba-sheets-agent dagi
# asosiy nusxaga bog'lanmaydi: u orqada qolishi yoki tozalanishi mumkin, nazorat esa shunda
# ham ishlashi kerak. Repo'da hisobot_nazorat.py o'zgarsa, shu skriptni qayta ishga
# tushiring. Qaysi commit'dan o'rnatilgani ~/.abba-nazorat/MANBA faylida yoziladi.
# Telegram uchun token o'sha .env dan o'qiladi (NAZORAT_ENV bilan boshqa fayl berish mumkin).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL=com.abba.hisobot-nazorat
DEST="$HOME/.abba-nazorat"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
ENVF="${NAZORAT_ENV:-$HOME/abba-sheets-agent/.env}"
DOMAIN="gui/$(id -u)"

to_xtat() {
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  # bootout tugamasdan bootstrap qilinsa «Input/output error» beradi
  for _ in 1 2 3 4 5; do
    launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || return 0
    sleep 1
  done
}

if [ "${1:-}" = "--ochir" ]; then
  to_xtat
  rm -f "$PLIST"
  echo "O'chirildi: $LABEL. Holat va log joyida qoldi: $DEST"
  exit 0
fi

mkdir -p "$DEST"
install -m 755 "$DIR/hisobot_nazorat.py" "$DEST/hisobot_nazorat.py"
SRC=$(git -C "$DIR" log -1 --format='%h %cs' -- hisobot_nazorat.py 2>/dev/null || true)
BR=$(git -C "$DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
if ! git -C "$DIR" diff --quiet HEAD -- hisobot_nazorat.py 2>/dev/null; then
  SRC="${SRC:-?} + commit qilinmagan o'zgarish"
fi
printf 'manba: %s (%s)\no'"'"'rnatildi: %s\n' "${SRC:-?}" "$BR" "$(date '+%F %T')" > "$DEST/MANBA"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$DEST/hisobot_nazorat.py</string>
        <string>--env</string>
        <string>$ENVF</string>
    </array>
    <!-- har 10 daqiqa: Mac 09:30 da uxlagan bo'lsa, uyg'ongandan keyin tekshiradi -->
    <key>StartInterval</key>
    <integer>600</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$DEST/nazorat.log</string>
    <key>StandardErrorPath</key>
    <string>$DEST/nazorat.log</string>
</dict>
</plist>
PLIST
plutil -lint "$PLIST" >/dev/null

to_xtat
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "OK: $LABEL yoqildi (har 10 daqiqa). $(head -1 "$DEST/MANBA")"
echo "Log: $DEST/nazorat.log · holat: $DEST/holat.json"
echo "Kanallarni sinash: /usr/bin/python3 $DEST/hisobot_nazorat.py --sinov --env $ENVF"
