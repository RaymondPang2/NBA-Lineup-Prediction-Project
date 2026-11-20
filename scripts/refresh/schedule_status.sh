#!/bin/zsh
# Is the daily refresh scheduled, when did it last run, and is the data current?
PROJECT="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL=com.lineuplab.daily-refresh
if launchctl print "gui/$(id -u)/$LABEL" >/tmp/lineuplab_launchd.$$ 2>&1; then
  echo "launchd: $LABEL is LOADED"
  grep -E "^\s*(state|runs|last exit code|run interval) =" /tmp/lineuplab_launchd.$$ | sed 's/^/  /'
  grep -A3 "event triggers" /tmp/lineuplab_launchd.$$ >/dev/null && echo "  calendar trigger: 07:00 daily (plus hourly catch-up checks)"
else
  echo "launchd: $LABEL is NOT loaded (enable it with scripts/refresh/install_schedule.sh)"
fi
rm -f /tmp/lineuplab_launchd.$$
echo
"$PROJECT/.venv/bin/python" -m nba_lineups.refresh --status
