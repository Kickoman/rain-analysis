#!/usr/bin/env python3
"""
push_ground_truth.py — Push Open-Meteo precipitation into the backend.
======================================================================

Fetches hourly precipitation for the site coordinates and pushes it as
the sensor ``openmeteo.precipitation`` through the measurements API. The
backend's metrics calculator reads it back as rain ground truth — the
backend itself never makes outbound HTTP requests, so this runs from
cron (kfrank: daily at 23:30 UTC, before the 00:00 UTC daily ML task).

Idempotent: re-pushing the same hours updates rows in place.

Usage:
  RAIN_BACKEND_KEY=ra_live_... python push_ground_truth.py \
      --backend-url http://127.0.0.1:7010 [--past-days 3]
"""

import argparse
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))

from fetch_openmeteo import DEFAULT_LAT, DEFAULT_LON  # single source of coordinates

SENSOR_NAME = "openmeteo.precipitation"


def fetch_precipitation(past_days: int) -> list[tuple[str, float]]:
    """Hourly (iso_timestamp_utc, mm) pairs for the trailing window."""
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": DEFAULT_LAT,
            "longitude": DEFAULT_LON,
            "hourly": "precipitation",
            "past_days": past_days,
            "forecast_days": 1,
            "timezone": "UTC",
        },
        timeout=60,
    )
    response.raise_for_status()
    hourly = response.json()["hourly"]
    return [
        (f"{t}:00+00:00", p)
        for t, p in zip(hourly["time"], hourly["precipitation"])
        if p is not None
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--backend-url", required=True)
    parser.add_argument("--api-key", default=os.environ.get("RAIN_BACKEND_KEY"))
    parser.add_argument("--past-days", type=int, default=3)
    args = parser.parse_args()

    if not args.api_key:
        print("[ERROR] No API key: pass --api-key or set RAIN_BACKEND_KEY", file=sys.stderr)
        return 1

    rows = fetch_precipitation(args.past_days)
    if not rows:
        print("[ERROR] Open-Meteo returned no precipitation data", file=sys.stderr)
        return 1

    payload = {
        "source": "openmeteo",
        "measurements": [
            {"sensor": SENSOR_NAME, "timestamp": ts, "value": str(mm)}
            for ts, mm in rows
        ],
    }
    response = requests.post(
        args.backend_url.rstrip("/") + "/api/v1/data/measurements",
        json=payload,
        headers={"X-API-Key": args.api_key},
        timeout=60,
    )
    response.raise_for_status()
    result = response.json()
    print(f"[DONE] {SENSOR_NAME}: {result['created']} created, "
          f"{result['updated']} updated, {len(result['skipped_invalid'])} skipped",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
