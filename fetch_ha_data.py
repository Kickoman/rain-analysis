#!/usr/bin/env python3
"""
fetch_ha_data.py — Export Home Assistant sensor history to CSV.
================================================================

Fetches history for specified entities from Home Assistant and exports
in the format expected by rain_analysis: entity_id,state,last_changed

Usage:
  python fetch_ha_data.py --days 7 --output data/ha_export.csv

Author: Karasik (AI assistant for Kickoman/rain-analysis)
"""

import argparse
import json
import os
import sys
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


DEFAULT_ENTITIES = [
    "sensor.datchik_klimata_temperatura",
    "sensor.datchik_klimata_vlazhnost",
    "sensor.rain_probability",
    "sensor.filtered_pressure",
]


def load_ha_config(config_path: str) -> dict:
    """Load HA URL and token from config file."""
    with open(config_path) as f:
        return json.load(f)


def fetch_history(url: str, token: str, entity_id: str,
                  start_time: datetime, end_time: datetime) -> list[dict]:
    """Fetch history for one entity from HA API."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    history_url = f"{url}/api/history/period/{start_time.isoformat()}"
    params = {
        "filter_entity_id": entity_id,
        "end_time": end_time.isoformat(),
        "minimal_response": "",
        "no_attributes": "",
    }

    try:
        r = requests.get(history_url, headers=headers, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        if data and len(data) > 0:
            records = data[0]
            # Add entity_id to each record (minimal_response doesn't include it)
            for rec in records:
                if "entity_id" not in rec:
                    rec["entity_id"] = entity_id
            return records
        return []
    except requests.RequestException as e:
        print(f"[ERROR] Failed to fetch {entity_id}: {e}", file=sys.stderr)
        return []


def export_to_csv(records: list[dict], output_path: str):
    """Write records to CSV in HA history export format."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["entity_id", "state", "last_changed"])

        for rec in records:
            writer.writerow([
                rec["entity_id"],
                rec["state"],
                rec["last_changed"],
            ])


def main():
    parser = argparse.ArgumentParser(
        description="Export Home Assistant sensor history to CSV"
    )
    parser.add_argument(
        "--config",
        default=os.path.expanduser("~/.openclaw/workspace/.ha_config.json"),
        help="Path to HA config JSON (url + token)",
    )
    parser.add_argument(
        "--entities",
        nargs="+",
        default=DEFAULT_ENTITIES,
        help="Entity IDs to export (space-separated)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days of history to fetch (default: 7)",
    )
    parser.add_argument(
        "--start",
        help="Start time (ISO 8601, overrides --days)",
    )
    parser.add_argument(
        "--end",
        help="End time (ISO 8601, default: now)",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output CSV file path",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress messages",
    )

    args = parser.parse_args()

    # Load config
    try:
        config = load_ha_config(args.config)
        url = config["url"]
        token = config["token"]
    except Exception as e:
        print(f"[ERROR] Failed to load config: {e}", file=sys.stderr)
        return 1

    # Determine time range
    if args.end:
        end_time = datetime.fromisoformat(args.end)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
    else:
        end_time = datetime.now(timezone.utc)

    if args.start:
        start_time = datetime.fromisoformat(args.start)
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
    else:
        start_time = end_time - timedelta(days=args.days)

    if not args.quiet:
        print(f"Fetching history from {start_time} to {end_time}")
        print(f"Entities: {args.entities}")

    # Fetch history for each entity
    all_records = []
    for entity_id in args.entities:
        if not args.quiet:
            print(f"  Fetching {entity_id}...", end=" ", flush=True)

        records = fetch_history(url, token, entity_id, start_time, end_time)

        if records:
            all_records.extend(records)
            if not args.quiet:
                print(f"{len(records)} entries")
        else:
            if not args.quiet:
                print("no data")

    if not all_records:
        print("[WARN] No data fetched from any entity", file=sys.stderr)
        return 1

    # Sort by timestamp (last_changed)
    all_records.sort(key=lambda r: r["last_changed"])

    # Export
    export_to_csv(all_records, args.output)

    if not args.quiet:
        print(f"\n✓ Exported {len(all_records)} records to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
