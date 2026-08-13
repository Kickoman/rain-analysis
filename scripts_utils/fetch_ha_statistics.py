#!/usr/bin/env python3
"""
fetch_ha_statistics.py — Export Home Assistant long-term statistics to CSV.
===========================================================================

Home Assistant's recorder purges raw state history after a few days (typically
10), but *long-term statistics* — hourly mean/min/max for sensors with a
numeric state_class — are kept indefinitely. This script reads those via the
WebSocket API and writes them in the same CSV shape as `fetch_ha_data.py`:

    entity_id,state,last_changed

so `rainlib.load_ha_csv()` reads the output without any changes. Each row is
one hourly statistic, timestamped at the start of the hour (UTC).

Usage:
  python fetch_ha_statistics.py --days 45 --output data/ha_stats.csv

Note: entities without a numeric state_class have no statistics at all
(`sensor.rain_probability` is one of them) — for those you still need
`fetch_ha_data.py`, limited to the recorder retention window.
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import websocket


# Sensors carrying the model's inputs. `sensor.rain_probability` is absent on
# purpose: it is a template sensor without state_class, so it has no statistics.
DEFAULT_ENTITIES = [
    "sensor.datchik_klimata_temperatura",
    "sensor.datchik_klimata_vlazhnost",
    "sensor.filtered_pressure",
    "sensor.outside_dew_point_spread_trend",
]

# How long to wait for a single WebSocket reply.
WS_TIMEOUT_SEC = 60


def load_ha_config(config_path: str) -> dict:
    """Load HA URL and token from config file."""
    with open(config_path) as f:
        return json.load(f)


def websocket_url(http_url: str) -> str:
    """Translate an http(s):// HA URL into its ws(s):// WebSocket endpoint."""
    parsed = urlparse(http_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}{parsed.path}/api/websocket"


def _recv_id(ws, msg_id: int) -> dict:
    """Read messages until the reply to `msg_id` arrives."""
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == msg_id:
            return msg


def fetch_statistics(url: str, token: str, entities: list[str],
                     start_time: datetime, end_time: datetime,
                     period: str = "hour") -> dict[str, list[dict]]:
    """Fetch long-term statistics for `entities` over a time range.

    Returns {entity_id: [stat_row, ...]}. Entities without statistics are
    simply absent from the result — Home Assistant does not error on them.
    """
    ws = websocket.create_connection(websocket_url(url), timeout=WS_TIMEOUT_SEC)
    try:
        ws.recv()  # auth_required
        ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth = json.loads(ws.recv())
        if auth.get("type") != "auth_ok":
            raise RuntimeError(f"HA authentication failed: {auth.get('message', auth.get('type'))}")

        ws.send(json.dumps({
            "id": 1,
            "type": "recorder/statistics_during_period",
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "statistic_ids": entities,
            "period": period,
        }))
        reply = _recv_id(ws, 1)
    finally:
        ws.close()

    if not reply.get("success", False):
        err = reply.get("error", {})
        raise RuntimeError(f"statistics_during_period failed: {err.get('code')}: {err.get('message')}")

    return reply.get("result", {}) or {}


def _stat_time(row: dict) -> datetime:
    """Parse a statistic row's `start` (epoch ms in current HA, ISO in older)."""
    start = row["start"]
    if isinstance(start, (int, float)):
        return datetime.fromtimestamp(start / 1000.0, tz=timezone.utc)
    parsed = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def to_records(result: dict[str, list[dict]], stat: str = "mean") -> list[dict]:
    """Flatten the statistics result into HA-history-shaped records."""
    records = []
    for entity_id, rows in result.items():
        for row in rows:
            value = row.get(stat)
            if value is None:
                continue
            records.append({
                "entity_id": entity_id,
                "state": value,
                "last_changed": _stat_time(row).isoformat(),
            })
    records.sort(key=lambda r: (r["last_changed"], r["entity_id"]))
    return records


def export_to_csv(records: list[dict], output_path: str):
    """Write records to CSV in HA history export format."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["entity_id", "state", "last_changed"])
        for rec in records:
            writer.writerow([rec["entity_id"], rec["state"], rec["last_changed"]])


def main():
    parser = argparse.ArgumentParser(
        description="Export Home Assistant long-term statistics to CSV"
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("HA_CONFIG", os.path.expanduser("~/.homeassistant/ha_config.json")),
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
        default=45,
        help="Number of days of statistics to fetch (default: 45)",
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
        "--period",
        default="hour",
        choices=["5minute", "hour", "day", "month"],
        help="Statistics aggregation period (default: hour)",
    )
    parser.add_argument(
        "--stat",
        default="mean",
        choices=["mean", "min", "max"],
        help="Which statistic to export as the state value (default: mean)",
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

    try:
        config = load_ha_config(args.config)
        url = config["url"]
        token = config["token"]
    except Exception as e:
        print(f"[ERROR] Failed to load config: {e}", file=sys.stderr)
        return 1

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
        print(f"Fetching {args.period}ly statistics from {start_time} to {end_time}")
        print(f"Entities: {args.entities}")

    try:
        result = fetch_statistics(url, token, args.entities, start_time, end_time, args.period)
    except Exception as e:
        # Sanitize in case the token leaked into the error text
        message = str(e).replace(token, "[REDACTED]") if token else str(e)
        print(f"[ERROR] Failed to fetch statistics: {type(e).__name__}: {message}", file=sys.stderr)
        return 1

    missing = [e for e in args.entities if not result.get(e)]
    if missing:
        print(
            f"[WARN] {len(missing)}/{len(args.entities)} entities have no statistics "
            f"(no numeric state_class?): {', '.join(missing)}",
            file=sys.stderr,
        )

    records = to_records(result, args.stat)
    if not records:
        print("[ERROR] No statistics returned for any entity", file=sys.stderr)
        return 1

    export_to_csv(records, args.output)

    if not args.quiet:
        for entity_id in args.entities:
            n = len(result.get(entity_id, []))
            print(f"  {entity_id}: {n} points")
        print(f"\n✓ Exported {len(records)} records to {args.output}")
        print(f"  Range: {records[0]['last_changed']} → {records[-1]['last_changed']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
