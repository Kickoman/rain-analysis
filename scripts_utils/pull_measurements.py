#!/usr/bin/env python3
"""
pull_measurements.py — Pull sensor measurements from the rain-analysis backend.
==============================================================================

The mirror image of push_measurements.py: reads the backend's measurements API
(GET /api/v1/data/measurements) and writes the same CSV shape the analysis
pipeline already understands (entity_id,state,last_changed), so the result can
be merged into data/archive/ha_hourly.csv with archive_ha_data.py and consumed
by rainlib.load_ha_csv unchanged.

This exists because the pipeline no longer has a Home Assistant to read from:
the backend is now the place where local sensor history accumulates.

Usage:
  python pull_measurements.py --backend-url https://example.org/rain-api \
      --start 2026-08-14T00:00:00+00:00 --end 2026-09-05T00:00:00+00:00 \
      --output data/ha_backend.csv

The API key is taken from --api-key or the RAIN_BACKEND_KEY env variable
(read scope is enough; write and admin keys satisfy it too).
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timezone

import requests

# The endpoint's own ceiling; one request per page of one sensor.
PAGE_SIZE = 5000
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5

# The six entities analysis/run_analysis.py maps in AnalysisConfig.ha_entities.
DEFAULT_SENSORS = [
    "sensor.datchik_klimata_temperatura",
    "sensor.datchik_klimata_vlazhnost",
    "sensor.filtered_pressure",
    "sensor.outside_dew_point_spread",
    "sensor.outside_dew_point_spread_trend",
    "sensor.rain_probability",
]


def get_page(session: requests.Session, url: str, api_key: str, params: list) -> dict:
    """GET one page with retry on 5xx / connection errors."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(
                url,
                params=params,
                headers={"X-API-Key": api_key},
                timeout=60,
            )
            if response.status_code < 500:
                response.raise_for_status()
                return response.json()
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except requests.RequestException as e:
            last_error = str(e)
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"Request failed after {MAX_RETRIES} attempts: {last_error}")


def normalise_timestamp(value: str) -> str:
    """API "…Z" / offset form → the "+00:00" form already in the archive CSV."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def iter_sensor_rows(session, endpoint, api_key, sensor, start, end, page_size):
    """Yield (entity_id, state, last_changed) for one sensor, paging to the end.

    One sensor per request on purpose: the endpoint pages over the combined
    row stream of everything asked for, so a multi-sensor request makes both
    `total` and the stop condition ambiguous and silently truncates.
    """
    page = 1
    seen = 0
    while True:
        params = [("sensor", sensor), ("page", page), ("page_size", page_size),
                  ("order", "asc")]
        if start:
            params.append(("start", start))
        if end:
            params.append(("end", end))

        payload = get_page(session, endpoint, api_key, params)
        series = payload.get("series") or []
        points = series[0].get("points", []) if series else []
        if not points:
            return

        for point in points:
            value = point.get("v")
            if value is None:
                value = point.get("raw")
            if value is None:
                continue
            yield sensor, str(value), normalise_timestamp(point["t"])

        seen += len(points)
        total = payload.get("total")
        if total is not None and seen >= total:
            return
        page += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--backend-url", required=True,
                        help="Backend base URL, e.g. https://example.org/rain-api")
    parser.add_argument("--api-key", default=os.environ.get("RAIN_BACKEND_KEY"),
                        help="API key with read scope (default: RAIN_BACKEND_KEY env)")
    parser.add_argument("--sensors", nargs="+", default=DEFAULT_SENSORS,
                        help="Sensor names to pull (default: the six pipeline entities)")
    parser.add_argument("--start", help="Start time ISO 8601 (inclusive)")
    parser.add_argument("--end", help="End time ISO 8601 (exclusive)")
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE,
                        help=f"Rows per request (default: {PAGE_SIZE}, the API ceiling)")
    parser.add_argument("--output", "-o", required=True, help="Output CSV path")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report per-sensor counts without writing the CSV")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Suppress progress output (errors still printed)")

    args = parser.parse_args()

    if not args.api_key:
        print("[ERROR] No API key: pass --api-key or set RAIN_BACKEND_KEY", file=sys.stderr)
        return 1

    endpoint = args.backend_url.rstrip("/") + "/api/v1/data/measurements"
    session = requests.Session()

    rows = []
    empty = []
    for sensor in args.sensors:
        sensor_rows = list(iter_sensor_rows(session, endpoint, args.api_key, sensor,
                                            args.start, args.end, args.page_size))
        if not sensor_rows:
            empty.append(sensor)
        rows.extend(sensor_rows)
        if not args.quiet:
            print(f"[INFO] {sensor}: {len(sensor_rows)} rows", file=sys.stderr)

    # A sensor that returns nothing is the failure mode that stays invisible
    # downstream: the pipeline happily builds a report without it.
    if empty:
        print(f"[ERROR] no rows for: {', '.join(empty)}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"[DRY] {len(rows)} rows, nothing written", file=sys.stderr)
        return 0

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["entity_id", "state", "last_changed"])
        writer.writerows(rows)

    print(f"[DONE] {len(rows)} rows → {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
