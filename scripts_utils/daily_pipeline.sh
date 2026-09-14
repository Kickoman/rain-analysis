#!/usr/bin/env bash
# Daily report pipeline. Replaces the openclaw runner that stopped on
# 2026-08-22 and was never a scheduled job to begin with.
#
# Runs on the server that hosts the backend, from cron. Everything it needs is
# already there: the sensor history lives in the backend, the ground-truth cron
# runs beside it, and the repo checkout is the same one the API serves from.
#
#   0 1 * * *  /home/<user>/rain-analysis/scripts_utils/daily_pipeline.sh
#
# One argument, optional: the report date (default: yesterday UTC). The whole
# thing is idempotent — re-running a date refreshes that report and re-pushes
# it, so recovering from a failed night is just running it again.
#
# Configuration comes from the environment (put it in the crontab or a file
# sourced before this script):
#   RAIN_BACKEND_URL   backend base URL, e.g. https://example.org/rain-api
#   RAIN_BACKEND_KEY   write-scoped API key
#   RAIN_REPO          repo checkout (default: the parent of this script)
#   RAIN_PYTHON        interpreter (default: $RAIN_REPO/.venv/bin/python)
#   RAIN_GIT_PUSH      "1" to commit and push the report (default: off)

set -euo pipefail

REPO="${RAIN_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${RAIN_PYTHON:-$REPO/.venv/bin/python}"
DAY="${1:-$(date -u -d yesterday +%F)}"
LOG_PREFIX="[$(date -u +%FT%TZ)] rain-daily $DAY"

cd "$REPO"
echo "$LOG_PREFIX: start"

if [[ -z "${RAIN_BACKEND_URL:-}" || -z "${RAIN_BACKEND_KEY:-}" ]]; then
    echo "$LOG_PREFIX: RAIN_BACKEND_URL and RAIN_BACKEND_KEY must be set" >&2
    exit 2
fi

# 1. Sensor history: the backend is the only place it accumulates now.
#    A generous overlap costs nothing — the archive merge is keyed on
#    (entity, timestamp), so re-pulled hours update in place.
"$PY" scripts_utils/pull_measurements.py \
    --backend-url "$RAIN_BACKEND_URL" \
    --start "$(date -u -d "$DAY - 3 days" +%FT00:00:00+00:00)" \
    --end   "$(date -u -d "$DAY + 1 day"  +%FT00:00:00+00:00)" \
    --output /tmp/rain_pull_$$.csv
"$PY" scripts_utils/archive_ha_data.py \
    --input /tmp/rain_pull_$$.csv --archive data/archive/ha_hourly.csv
rm -f /tmp/rain_pull_$$.csv

# 2. Ground truth and the independent check. The forecast series is the one
#    the backend also stores; mixing it with the ERA5 archive would change the
#    rain base rate threefold, so only this one is refreshed.
"$PY" scripts_utils/fetch_openmeteo.py --start 2026-07-18 --use-forecast \
    --output /tmp/rain_om_$$.json
"$PY" scripts_utils/trim_forecast.py /tmp/rain_om_$$.json data/archive/om_backfill_forecast.json
rm -f /tmp/rain_om_$$.json

"$PY" scripts_utils/fetch_meteostat.py --start 2026-06-15 \
    --end "$(date -u +%F)" --output data/archive/ms_backfill.json

# 3. The report itself, pushed to the backend's reports API.
"$PY" scripts_utils/make_onset_report.py --date "$DAY" --push

# 4. Optional: keep the repo as the durable copy. Off by default so a server
#    without push rights still produces reports.
if [[ "${RAIN_GIT_PUSH:-0}" == "1" ]]; then
    git add reports/ data/archive/ >/dev/null
    if git diff --cached --quiet; then
        echo "$LOG_PREFIX: nothing to commit"
    else
        git commit -q -m "report: rain onset analysis $DAY"
        git push -q origin HEAD
        echo "$LOG_PREFIX: committed and pushed"
    fi
fi

echo "$LOG_PREFIX: done"
