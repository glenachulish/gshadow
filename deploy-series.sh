#!/usr/bin/env bash
# Deploy the series-grouping feature to the Pi, with safety checks.
# Run from ~/gshadow on the Mac AFTER you've placed the new/edited files
# and committed them. This script does the rsync, restart, and — crucially —
# checks the service came back up, printing the real traceback if it didn't.
#
# It does NOT commit or push for you (so you stay in control of git). Do that
# first, then run this.

set -euo pipefail

PI=pi@ceol-pi.local
PI_PATH=/home/pi/gshadow

echo "==> Confirming we're in the right directory"
pwd
if [ ! -f app/main.py ] || [ ! -f app/series.py ]; then
  echo "ERROR: app/main.py or app/series.py not found. Are you in ~/gshadow with the new files in place?"
  exit 1
fi

echo
echo "==> git status (staging check — confirm .env and data/ are NOT listed)"
git status --short

echo
echo "==> rsync to the Pi (excludes venv, data, audio, staging, .git)"
rsync -av --delete \
  --exclude .venv --exclude data --exclude audio --exclude staging --exclude .git \
  ./ "${PI}:${PI_PATH}/"

echo
echo "==> Restarting the gshadow service and checking it came back up"
ssh -t "${PI}" '
  sudo systemctl restart gshadow
  sleep 3
  if systemctl is-active --quiet gshadow; then
    echo "SERVICE OK: gshadow is active (running)"
    systemctl status gshadow --no-pager | head -5
  else
    echo "SERVICE FAILED TO START — last 50 log lines follow:"
    echo "------------------------------------------------------------"
    journalctl -u gshadow -n 50 --no-pager -l
    echo "------------------------------------------------------------"
    echo "The deploy reached the Pi but the app did not start. See traceback above."
    echo "To roll back: git revert HEAD on the Mac, then re-run this script."
    exit 1
  fi
'

echo
echo "==> Done. Quick manual checks:"
echo "    1. Open the site, go to the 'Other Audio' category page."
echo "    2. As admin/uploader you'll see a '+ New series (book)' link — create one."
echo "    3. Go to 'New collection', confirm the 'Series' dropdown lists it."
echo "    4. Create a collection assigned to that series; confirm it appears"
echo "       under the series card (not in the loose list) and the breadcrumb"
echo "       on the collection page reads Home > Other Audio > <series> > <title>."
