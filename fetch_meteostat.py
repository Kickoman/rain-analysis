#!/usr/bin/env python3
"""
fetch_meteostat.py — Fetch historical weather data from Meteostat API.
=======================================================================

Downloads temperature, humidity, precipitation, and pressure data for Minsk
from Meteostat's station 26850 and saves in JSON format for analysis.

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


def fetch_data(station: str, start_date: str, end_date: str) -> dict:
    """Fetch weather data from Meteostat API."""
    
    url = "https://d.meteostat.net/app/proxy/stations/hourly"
    params = {
        "station": station,
        "tz": "UTC",
        "start": start_date,
        "end": end_date,
    }
    
    print(f"Fetching from Meteostat...", file=sys.stderr)
    print(f"  Station: {station}", file=sys.stderr)
    print(f"  Range: {start_date} to {end_date}", file=sys.stderr)
    
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data
    except requests.RequestException as e:
        print(f"[ERROR] Failed to fetch: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON response: {e}", file=sys.stderr)
        sys.exit(1)


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

    # Save
    with open(args.output, 'w') as f:
        json.dump(data, f, indent=2)

    if not args.quiet:
        records = data.get('data', [])
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
