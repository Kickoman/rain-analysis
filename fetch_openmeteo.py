#!/usr/bin/env python3
"""
fetch_openmeteo.py — Fetch historical weather data from Open-Meteo API.
========================================================================

Downloads temperature, humidity, and precipitation data for Minsk from
Open-Meteo's archive/forecast API and saves in JSON format for analysis.

Usage:
  python fetch_openmeteo.py --days 7 --output data/openmeteo.json

Author: Karasik (AI assistant for Kickoman/rain-analysis)
"""

import argparse
import sys
import json
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError


# Minsk coordinates
DEFAULT_LAT = 53.930716
DEFAULT_LON = 27.596646


def fetch_data(lat: float, lon: float, start_date: str, end_date: str, 
               use_forecast: bool = False) -> dict:
    """Fetch weather data from Open-Meteo API."""
    
    if use_forecast:
        # Forecast API uses past_days relative to TODAY, not end_date
        today = datetime.now(timezone.utc).date()
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        
        # Validate that end_date is today
        if end_dt != today:
            print(f"[ERROR] --use-forecast requires --end to be today ({today}), got {end_date}", 
                  file=sys.stderr)
            print(f"        Forecast API fetches data relative to wall-clock today, not arbitrary --end dates.",
                  file=sys.stderr)
            sys.exit(1)
        
        # Calculate past_days from start_date to today
        days_back = (today - start_dt).days
        
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,relative_humidity_2m,precipitation,rain,showers"
            f"&timezone=UTC"
            f"&past_days={days_back}"
        )
        
        print(f"[INFO] Forecast mode: fetching {days_back} days back from today ({today})", 
              file=sys.stderr)
    else:
        # Use archive API
        url = (
            f"https://archive-api.open-meteo.com/v1/archive?"
            f"latitude={lat}&longitude={lon}"
            f"&start_date={start_date}&end_date={end_date}"
            f"&hourly=temperature_2m,relative_humidity_2m,precipitation,rain,showers"
            f"&timezone=UTC"
        )
    
    print(f"Fetching from Open-Meteo...", file=sys.stderr)
    print(f"  URL: {url}", file=sys.stderr)
    
    try:
        req = Request(url)
        req.add_header('User-Agent', 'rain-analysis/1.0')
        
        with urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data
    except URLError as e:
        print(f"[ERROR] Failed to fetch: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON response: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch historical weather data from Open-Meteo"
    )
    parser.add_argument(
        "--lat",
        type=float,
        default=DEFAULT_LAT,
        help=f"Latitude (default: {DEFAULT_LAT} - Minsk)",
    )
    parser.add_argument(
        "--lon",
        type=float,
        default=DEFAULT_LON,
        help=f"Longitude (default: {DEFAULT_LON} - Minsk)",
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
        "--use-forecast",
        action="store_true",
        help="Use forecast API instead of archive API (for recent data)",
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
    data = fetch_data(args.lat, args.lon, start_date, end_date, args.use_forecast)

    # Save
    with open(args.output, 'w') as f:
        json.dump(data, f, indent=2)

    if not args.quiet:
        hourly_points = len(data.get('hourly', {}).get('time', []))
        print(f"\n✓ Saved {hourly_points} hourly data points to {args.output}", 
              file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
