#!/bin/bash
# install_live_cron.sh — Install cron entries for live trading.
#
# Adds three weekday entries:
#   09:25  start live_ex1.py (polls bars + places orders)
#   14:35  run reconcile_live.py (compares state vs broker fills)
#   14:36  git commit + push live state files
#
# The runner self-terminates after 14:30 once all positions are flat.
#
# Run once:  bash /home/ben/Signal/install_live_cron.sh

set -euo pipefail

NEW_ENTRIES=$(cat <<'EOF'
# Signal Reader LIVE — start runner pre-market (weekdays, 9:25 AM)
25 9 * * 1-5 /home/ben/Signal/venv/bin/python3 -u /home/ben/Signal/live_ex1.py >> /home/ben/Signal/logs/live_ex1.log 2>&1
# Signal Reader LIVE — reconcile broker vs state after EOD (weekdays, 2:35 PM)
35 14 * * 1-5 /home/ben/Signal/venv/bin/python3 /home/ben/Signal/reconcile_live.py >> /home/ben/Signal/logs/reconcile.log 2>&1
# Signal Reader LIVE — git push live state + trades file (weekdays, 2:36 PM)
36 14 * * 1-5 cd /home/ben/Signal && git add live_state.json trades_live.json logs/live_ex1.log 2>/dev/null && git commit -m "Live $(date +\%Y-\%m-\%d) EOD reconcile" 2>/dev/null && git push 2>/dev/null || true
EOF
)

# Idempotent install: skip if already present
if crontab -l 2>/dev/null | grep -q "Signal Reader LIVE"; then
    echo "Live cron entries already installed. Nothing to do."
    exit 0
fi

# Append to existing crontab
(crontab -l 2>/dev/null; echo ""; echo "$NEW_ENTRIES") | crontab -

echo "✓ Live cron entries installed:"
echo "  09:25  start live_ex1.py"
echo "  14:35  run reconcile_live.py"
echo "  14:36  git commit + push"
echo ""
echo "Verify with: crontab -l | grep 'LIVE'"
