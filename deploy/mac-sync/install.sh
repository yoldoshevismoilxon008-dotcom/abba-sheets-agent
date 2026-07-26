#!/bin/bash
# Mac-sync o'rnatish: server'dan hisobotlarni soatiga 1 tortadigan launchd job.
#   ./install.sh root@SERVER_IP
set -euo pipefail
DEST=${1:?"Ishlatish: install.sh root@SERVER_IP"}
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$DIR/../.." && pwd)"
LABEL=com.abba.sheets-sync
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "SSH_DEST=$DEST" > "$DIR/server.conf"
chmod +x "$DIR/sync_from_server.sh"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$DIR/sync_from_server.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>3600</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$APP/data/logs/sync-launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$APP/data/logs/sync-launchd.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "OK: $LABEL o'rnatildi — har soatda $DEST dan hisobotlar vault'ga tortiladi."
echo "Birinchi sync hozir ishga tushdi; log: $APP/data/logs/sync.log"
