#!/usr/bin/env python3
"""
push_measurements.py — Push sensor measurements to the rain-analysis backend.
=============================================================================

Feeds the backend's measurements API (POST /api/v1/data/measurements) from
either an existing CSV archive (entity_id,state,last_changed) or directly
from Home Assistant history. Serves three purposes:

  * initial backfill of recorder history into the backend,
  * gap repair after missed HA push automations,
  * pushing ground truth (e.g. Open-Meteo precipitation) as measurements.

The ingest endpoint is idempotent (upsert on sensor+timestamp), so re-running
this script over the same data is always safe.

Usage:
  python push_measurements.py --backend-url http://localhost:8000 \
      --from-csv data/archive/ha_hourly.csv
  python push_measurements.py --backend-url http://localhost:8000 \
      --from-ha --days 7 --entities sensor.rain_probability

The API key is taken from --api-key or the RAIN_BACKEND_KEY env variable
(a key with write scope is required).
"""

import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

BATCH_SIZE = 500
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5

# Must match the backend's sensor-name validation; rows failing it would
# fail request validation for the whole batch, so filter them client-side.
SENSOR_NAME_RE = re.compile(r"^[a-z0-9_.]+$")


def iter_csv_rows(path: str):
    """Yield (entity_id, state, iso_timestamp) from an HA export CSV."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row["entity_id"], row["state"], row["last_changed"]


def iter_ha_rows(config_path: str, entities: list[str], start, end):
    """Yield rows from HA history using the shared fetcher."""
    from fetch_ha_data import fetch_history, load_ha_config

    config = load_ha_config(config_path)
    for entity_id in entities:
        records = fetch_history(config["url"], config["token"], entity_id, start, end)
        for rec in records:
            yield entity_id, rec.get("state", ""), rec.get("last_changed", "")


def build_batches(rows, source: str):
    """Group raw rows into ingest payloads, skipping obvious non-values."""
    batch = []
    for entity_id, state, ts in rows:
        if not ts or state is None:
            continue
        if not SENSOR_NAME_RE.match(entity_id) or len(entity_id) > 128:
            print(f"[WARN] skipping invalid entity name: {entity_id!r}", file=sys.stderr)
            continue
        batch.append({"sensor": entity_id, "timestamp": ts, "value": str(state)})
        if len(batch) >= BATCH_SIZE:
            yield {"source": source, "measurements": batch}
            batch = []
    if batch:
        yield {"source": source, "measurements": batch}


def post_batch(session: requests.Session, url: str, api_key: str, payload: dict) -> dict:
    """POST one batch with retry on 5xx / connection errors."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.post(
                url,
                json=payload,
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
    raise RuntimeError(f"Batch failed after {MAX_RETRIES} attempts: {last_error}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--backend-url", required=True, help="Backend base URL, e.g. http://localhost:8000")
    parser.add_argument("--api-key", default=os.environ.get("RAIN_BACKEND_KEY"),
                        help="Write-scoped API key (default: RAIN_BACKEND_KEY env)")
    parser.add_argument("--source", default="backfill", help="Source label stored with the rows")

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--from-csv", help="CSV file (entity_id,state,last_changed)")
    input_group.add_argument("--from-ha", action="store_true", help="Fetch from HA history API")

    parser.add_argument("--config",
                        default=os.environ.get("HA_CONFIG", os.path.expanduser("~/.homeassistant/ha_config.json")),
                        help="HA config JSON for --from-ha")
    parser.add_argument("--entities", nargs="+",
                        default=["sensor.rain_probability",
                                 "sensor.datchik_klimata_temperatura",
                                 "sensor.datchik_klimata_vlazhnost",
                                 "sensor.filtered_pressure"],
                        help="Entities for --from-ha")
    parser.add_argument("--days", type=int, default=7, help="Days of HA history for --from-ha")
    parser.add_argument("--since", help="Start time ISO 8601 (overrides --days)")
    parser.add_argument("--until", help="End time ISO 8601 (default: now)")

    args = parser.parse_args()

    if not args.api_key:
        print("[ERROR] No API key: pass --api-key or set RAIN_BACKEND_KEY", file=sys.stderr)
        return 1

    if args.from_csv:
        rows = iter_csv_rows(args.from_csv)
    else:
        end = datetime.fromisoformat(args.until) if args.until else datetime.now(timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if args.since:
            start = datetime.fromisoformat(args.since)
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
        else:
            start = end - timedelta(days=args.days)
        rows = iter_ha_rows(args.config, args.entities, start, end)

    endpoint = args.backend_url.rstrip("/") + "/api/v1/data/measurements"
    session = requests.Session()

    totals = {"accepted": 0, "created": 0, "updated": 0, "skipped": 0, "batches": 0}
    for payload in build_batches(rows, args.source):
        result = post_batch(session, endpoint, args.api_key, payload)
        totals["accepted"] += result.get("accepted", 0)
        totals["created"] += result.get("created", 0)
        totals["updated"] += result.get("updated", 0)
        totals["skipped"] += len(result.get("skipped_invalid", []))
        totals["batches"] += 1
        print(f"[INFO] batch {totals['batches']}: +{result.get('created', 0)} new, "
              f"{result.get('updated', 0)} updated, "
              f"{len(result.get('skipped_invalid', []))} skipped", file=sys.stderr)

    print(f"[DONE] {totals['batches']} batches: {totals['created']} created, "
          f"{totals['updated']} updated, {totals['skipped']} skipped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
