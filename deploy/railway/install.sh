#!/bin/bash
# Mac'da hisobot-pull o'rnatish (soatiga 1 launchd):
#   ./install.sh git@github.com:USER/abba-hisobotlar.git
set -euo pipefail
URL=${1:?"Ishlatish: install.sh <hisobotlar repo URL (ssh)>"}
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$DIR/../.." && pwd)"
LABEL=com.abba.reports-pull
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "REPORTS_REPO_URL=$URL" > "$DIR/repo.conf"
chmod +x "$DIR/vault_pull.sh"

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
        <string>$DIR/vault_pull.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>3600</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$APP/data/logs/reports-pull-launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$APP/data/logs/reports-pull-launchd.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "OK: $LABEL — har soatda $URL dan vault'ga hisobot tortiladi."
echo "Log: $APP/data/logs/reports-pull.log"
