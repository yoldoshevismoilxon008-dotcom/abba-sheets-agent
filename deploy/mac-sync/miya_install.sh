#!/bin/bash
# Ikkinchi miya yig'uvchisi — Mac'ga o'rnatish / yangilash.
#
#   bash deploy/mac-sync/miya_install.sh              # o'rnatish + darhol bitta yig'ish
#   bash deploy/mac-sync/miya_install.sh --obsidian   # + vault'ni Obsidian'da ochish
#   bash deploy/mac-sync/miya_install.sh --ochir      # launchd'ni o'chirish (yozuvlar qoladi)
#
# Kod ~/.abba-miya/miya/ ga NUSXA qilinadi (worktree yoki branch o'chsa ham ishlayveradi);
# qaysi commit ekani ~/.abba-miya/MANBA da. launchd com.abba.miya har soatda ishlaydi.
# Holat: ~/.abba-miya/state/ · log: ~/.abba-miya/miya.log va launchd.log
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$DIR/../.." && pwd)"
DEST="$HOME/.abba-miya"
LABEL=com.abba.miya
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PY=/usr/bin/python3

if [ "${1:-}" = "--ochir" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootout "gui/$(id -u)/$LABEL-xulosa" 2>/dev/null || true
  rm -f "$PLIST" "$HOME/Library/LaunchAgents/$LABEL-xulosa.plist"
  echo "OK: $LABEL va $LABEL-xulosa o'chirildi. Vault'dagi yozuvlar va $DEST joyida qoldi."
  exit 0
fi

mkdir -p "$DEST/state"
rm -rf "$DEST/miya.yangi"
cp -R "$DIR/miya" "$DEST/miya.yangi"
find "$DEST/miya.yangi" -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$DEST/miya.eski"
[ -d "$DEST/miya" ] && mv "$DEST/miya" "$DEST/miya.eski"
mv "$DEST/miya.yangi" "$DEST/miya"
rm -rf "$DEST/miya.eski"
{
  echo "commit: $(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo '?')"
  echo "branch: $(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  echo "o'rnatildi: $(date '+%F %T')"
} > "$DEST/MANBA"

# claude.ai artifactlari urug'i (ixtiyoriy, bir martalik): MIYA_ARTIFACT_URUG=/yo'l/urug.json
if [ -n "${MIYA_ARTIFACT_URUG:-}" ] && [ -f "$MIYA_ARTIFACT_URUG" ]; then
  cp "$MIYA_ARTIFACT_URUG" "$DEST/state/artifactlar_urug.json"
fi

# Sinov: o'rnatishdan oldin diskka yozmasdan bir yurish (xato bo'lsa launchd qo'yilmaydi)
(cd "$DEST" && PYTHONDONTWRITEBYTECODE=1 "$PY" -m miya --quruq >/dev/null) || {
  echo "XATO: quruq yurish yiqildi — launchd qo'yilmadi. Log: $DEST/miya.log"; exit 1; }

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <!-- Ikkinchi miya yig'uvchisi: Claude sessiyalari, skillar, kod, WALL-E kunlari → ~/claude-brain -->
    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>-m</string>
        <string>miya</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$DEST</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONDONTWRITEBYTECODE</key>
        <string>1</string>
    </dict>
    <key>StartInterval</key>
    <integer>3600</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>Nice</key>
    <integer>10</integer>
    <key>LowPriorityIO</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$DEST/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$DEST/launchd.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "OK: $LABEL o'rnatildi ($(head -1 "$DEST/MANBA")). Har soatda ishlaydi; birinchi yig'ish hozir boshlandi."
# Kechki xulosa jadvali ($LABEL-xulosa) sozlamaga moslanadi: yoqilgan bo'lsa qayta qo'yiladi
(cd "$DEST" && PYTHONDONTWRITEBYTECODE=1 "$PY" -c \
  'from miya import xulosa; print("xulosa:", xulosa.jadval_yangila())') || true
echo "Holat sahifasi: ~/claude-brain/tizim/miya-holati.md · log: $DEST/miya.log"

if [ "${1:-}" = "--obsidian" ]; then
  sleep 20
  (cd "$DEST" && "$PY" -m miya --obsidian-och)
fi
