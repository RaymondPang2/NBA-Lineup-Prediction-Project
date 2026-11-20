#!/bin/zsh
# Disable the daily refresh and remove the LaunchAgent. Data and logs are kept.
set -euo pipefail
LABEL=com.lineuplab.daily-refresh
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "stopped $LABEL" || echo "$LABEL was not loaded"
rm -f "$PLIST" && echo "removed $PLIST"
