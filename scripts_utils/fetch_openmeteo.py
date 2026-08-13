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
USER_AGENT = "rain-analysis/1.0 (+https://github.com/Kickoman/rain-analysis)"


# Hourly variables requested from both the forecast and archive endpoints.
# surface_pressure is the station-level reading, the like-for-like reference for
# the local barometer; Meteostat's `pres` is reduced to sea level, so comparing
# the two shows Minsk's ~220 m elevation as a ~26 hPa "sensor bias".
HOURLY_VARIABLES = (
    "temperature_2m,relative_humidity_2m,dew_point_2m,"
    "precipitation,rain,showers,surface_pressure"
)

def generate_mock_data(start_date: str, end_date: str) -> dict:
    """Generate mock Open-Meteo API response for testing."""
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    
    # Generate hourly timestamps
    times = []
    temps = []
    humidities = []
    precips = []
    rains = []
    showers = []
    
    current = start_dt
    while current <= end_dt:
        for hour in range(24):
            timestamp = current.replace(hour=hour, minute=0, second=0)
            if timestamp > end_dt.replace(hour=23, minute=59):
                break
            times.append(timestamp.strftime("%Y-%m-%dT%H:%M"))
            temps.append(15.0 + (hour / 24.0) * 5.0)  # Mock temperature variation
            humidities.append(70 + (hour % 12))  # Mock humidity
            precips.append(0.1 if hour % 6 == 0 else 0.0)  # Mock precipitation
            rains.append(0.1 if hour % 6 == 0 else 0.0)
            showers.append(0.0)
        current += timedelta(days=1)
    
    return {
        "latitude": DEFAULT_LAT,
        "longitude": DEFAULT_LON,
        "generationtime_ms": 0.123,
        "utc_offset_seconds": 0,
        "timezone": "UTC",
        "timezone_abbreviation": "UTC",
        "elevation": 234.0,
        "hourly_units": {
            "time": "iso8601",
            "temperature_2m": "°C",
            "relative_humidity_2m": "%",
            "precipitation": "mm",
            "rain": "mm",
            "showers": "mm"
        },
        "hourly": {
            "time": times,
            "temperature_2m": temps,
            "relative_humidity_2m": humidities,
            "precipitation": precips,
            "rain": rains,
            "showers": showers
        }
    }


def fetch_data(lat: float, lon: float, start_date: str, end_date: str, 
               use_forecast: bool = False, dry_run: bool = False) -> dict:
    """Fetch weather data from Open-Meteo API."""
    
    if use_forecast:
        # Forecast API uses past_days relative to TODAY, not end_date
        today = datetime.now(timezone.utc).date()
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        
        # Validate that end_date is today (even in dry-run mode)
        if end_dt != today:
            print(f"[ERROR] --use-forecast requires --end to be today ({today}), got {end_date}", 
                  file=sys.stderr)
            print(f"        Forecast API fetches data relative to wall-clock today, not arbitrary --end dates.",
                  file=sys.stderr)
            sys.exit(1)
        
        # Calculate past_days from start_date to today
        days_back = (today - start_dt).days
        
        if dry_run:
            print(f"[DRY-RUN] Returning mock data instead of making HTTP request", file=sys.stderr)
            return generate_mock_data(start_date, end_date)
        
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}"
            f"&hourly={HOURLY_VARIABLES}"
            f"&timezone=UTC"
            f"&past_days={days_back}"
        )
        
        print(f"[INFO] Forecast mode: fetching {days_back} days back from today ({today})", 
              file=sys.stderr)
    else:
        if dry_run:
            print(f"[DRY-RUN] Returning mock data instead of making HTTP request", file=sys.stderr)
            return generate_mock_data(start_date, end_date)
        
        # Use archive API
        url = (
            f"https://archive-api.open-meteo.com/v1/archive?"
            f"latitude={lat}&longitude={lon}"
            f"&start_date={start_date}&end_date={end_date}"
            f"&hourly={HOURLY_VARIABLES}"
            f"&timezone=UTC"
        )
    
    print(f"Fetching from Open-Meteo...", file=sys.stderr)
    print(f"  URL: {url}", file=sys.stderr)
    
    try:
        req = Request(url)
        req.add_header('User-Agent', USER_AGENT)
        
        with urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            # Validate response contains data
            hourly_points = len(data.get('hourly', {}).get('time', []))
            if hourly_points == 0:
                print(f"[ERROR] No data returned (empty result). "
                      f"Possible causes: date range invalid, coordinates out of bounds, or API issue.",
                      file=sys.stderr)
                sys.exit(1)
            
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip HTTP request and return mock data for testing",
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
    data = fetch_data(args.lat, args.lon, start_date, end_date, args.use_forecast, args.dry_run)

    # Validate that we got data
    hourly_points = len(data.get('hourly', {}).get('time', []))
    if hourly_points == 0:
        print(f"[ERROR] No hourly data points returned from Open-Meteo", file=sys.stderr)
        return 1

    # Save
    with open(args.output, 'w') as f:
        json.dump(data, f, indent=2)

    if not args.quiet:
        print(f"\n✓ Saved {hourly_points} hourly data points to {args.output}", 
              file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
