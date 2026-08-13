#!/usr/bin/env python3
"""
fetch_meteostat.py — Fetch historical weather data from Meteostat API.
=======================================================================

Downloads temperature, humidity, precipitation, and pressure data for Minsk
from Meteostat's station 26850 and saves in JSON format for analysis.

**Note:** This script uses Meteostat's internal proxy endpoint
(d.meteostat.net/app/proxy/stations/hourly), which is not part of their
documented public API. It may change or become unavailable without notice.

Usage:
  python fetch_meteostat.py --days 7 --output data/meteostat.json

Author: Karasik (AI assistant for Kickoman/rain-analysis)
"""

import argparse
import sys
import json
from datetime import datetime, timedelta, timezone

import requests


DEFAULT_STATION = "26850"  # Minsk
USER_AGENT = "rain-analysis/1.0 (+https://github.com/Kickoman/rain-analysis)"

# The API rejects any single request spanning more than 30 days:
#   {"detail": "Tried to request data for 43 days. Maximum is 30."}
# Longer ranges are split into chunks and stitched back together.
MAX_DAYS_PER_REQUEST = 30


def date_chunks(start_date: str, end_date: str, max_days: int = MAX_DAYS_PER_REQUEST):
    """Split an inclusive date range into chunks of at most `max_days`."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    while start <= end:
        chunk_end = min(start + timedelta(days=max_days - 1), end)
        yield start.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")
        start = chunk_end + timedelta(days=1)


def fetch_chunk(station: str, start_date: str, end_date: str) -> dict:
    """Fetch one within-limit range from the Meteostat API."""
    url = "https://d.meteostat.net/app/proxy/stations/hourly"
    params = {
        "station": station,
        "tz": "UTC",
        "start": start_date,
        "end": end_date,
    }
    headers = {
        "User-Agent": USER_AGENT,
    }

    print(f"  Range: {start_date} to {end_date}", file=sys.stderr)

    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        # The API explains range violations in the body; surface that instead of
        # a bare status code.
        detail = ""
        response = getattr(e, "response", None)
        if response is not None:
            try:
                detail = f" — {response.json().get('detail', '')}"
            except ValueError:
                detail = f" — {response.text[:200]}"
        print(f"[ERROR] Failed to fetch: {e}{detail}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON response: {e}", file=sys.stderr)
        sys.exit(1)


def fetch_data(station: str, start_date: str, end_date: str) -> dict:
    """Fetch weather data from Meteostat, chunking ranges over the API limit."""
    print(f"Fetching from Meteostat...", file=sys.stderr)
    print(f"  Station: {station}", file=sys.stderr)

    merged = None
    by_time = {}

    for chunk_start, chunk_end in date_chunks(start_date, end_date):
        data = fetch_chunk(station, chunk_start, chunk_end)
        if merged is None:
            merged = {k: v for k, v in data.items() if k != "data"}
        for record in data.get("data", []):
            by_time[record.get("time")] = record

    if not by_time:
        print(f"[ERROR] No data returned (empty result). "
              f"Possible causes: station offline, date range invalid, or blocked.",
              file=sys.stderr)
        sys.exit(1)

    merged = merged or {}
    merged["data"] = [by_time[t] for t in sorted(by_time)]
    return merged


def main():
    parser = argparse.ArgumentParser(
        description="Fetch historical weather data from Meteostat"
    )
    parser.add_argument(
        "--station",
        default=DEFAULT_STATION,
        help=f"Meteostat station ID (default: {DEFAULT_STATION} - Minsk)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days of history to fetch (default: 7)",
    )
    parser.add_argument(
        "--start",
        help="Start date (YYYY-MM-DD, overrides --days)",
    )
    parser.add_argument(
        "--end",
        help="End date (YYYY-MM-DD, default: today)",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output JSON file path",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress messages",
    )

    args = parser.parse_args()

    # Determine date range
    if args.end:
        end_date = args.end
    else:
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if args.start:
        start_date = args.start
    else:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=args.days)
        start_date = start_dt.strftime("%Y-%m-%d")

    if not args.quiet:
        print(f"Date range: {start_date} to {end_date}", file=sys.stderr)

    # Fetch data
    data = fetch_data(args.station, start_date, end_date)

    # Validate that we got data
    records = data.get('data', [])
    if not records:
        print(f"[ERROR] No hourly records returned from Meteostat", file=sys.stderr)
        return 1

    # Save
    with open(args.output, 'w') as f:
        json.dump(data, f, indent=2)

    if not args.quiet:
        print(f"\n✓ Saved {len(records)} hourly records to {args.output}", 
              file=sys.stderr)
        
        # Show what data we have
        if records:
            sample = records[0]
            fields = list(sample.keys())
            print(f"  Fields: {', '.join(fields)}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
