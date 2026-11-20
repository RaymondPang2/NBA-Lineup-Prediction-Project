#!/bin/zsh
# Enable the daily 07:00 refresh (macOS launchd, current user only). Safe to rerun: it reinstalls.
set -euo pipefail
PROJECT="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL=com.lineuplab.daily-refresh
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
[[ -x "$PROJECT/.venv/bin/python" ]] || { echo "missing $PROJECT/.venv (create the virtualenv first)"; exit 1; }
mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT/data/logs"
sed "s#__PROJECT__#$PROJECT#g" "$PROJECT/scripts/refresh/$LABEL.plist.template" > "$PLIST"
plutil -lint "$PLIST" >/dev/null
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
echo "installed $PLIST"
echo "daily refresh enabled: 07:00 local time, hourly catch-up checks, logs in $PROJECT/data/logs/"
echo "check it with: scripts/refresh/schedule_status.sh"
