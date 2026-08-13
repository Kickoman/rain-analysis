#!/usr/bin/env python3
"""
archive_ha_data.py — Accumulate Home Assistant exports into a durable archive.
==============================================================================

Home Assistant discards history on its own schedule: raw states after the
recorder retention window, and long-term statistics whenever the database is
rebuilt. Anything not copied out before then is gone for good. This script
merges a fresh export into an append-only archive so the dataset keeps growing
past whatever Home Assistant itself still holds.

Merging is idempotent: rows are keyed on (entity_id, last_changed), so
re-running over overlapping exports never duplicates. When a key appears in
both the archive and the new export, the new value wins — a later fetch of the
same hour is based on more complete data than an earlier partial one.

Usage:
  python fetch_ha_statistics.py --days 45 --output data/ha_stats.csv
  python archive_ha_data.py --input data/ha_stats.csv

The archive uses the same three-column shape as the fetchers
(entity_id,state,last_changed), so `rainlib.load_ha_csv()` reads it directly.
"""

import argparse
import csv
import sys
from pathlib import Path

FIELDNAMES = ["entity_id", "state", "last_changed"]

DEFAULT_ARCHIVE = "data/archive/ha_hourly.csv"


def read_csv(path: Path) -> dict[tuple[str, str], dict]:
    """Read an HA-shaped CSV into {(entity_id, last_changed): row}."""
    if not path.exists():
        return {}

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = set(FIELDNAMES) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path}: missing column(s) {sorted(missing)}")
        return {
            (row["entity_id"], row["last_changed"]): row
            for row in reader
            if row.get("entity_id") and row.get("last_changed")
        }


def write_csv(path: Path, rows: dict[tuple[str, str], dict]):
    """Write rows sorted by time then entity, atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")

    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for key in sorted(rows, key=lambda k: (k[1], k[0])):
            row = rows[key]
            writer.writerow({k: row[k] for k in FIELDNAMES})

    tmp.replace(path)


def merge(archive: dict, incoming: dict) -> tuple[dict, int, int]:
    """Merge incoming rows over the archive. Returns (merged, added, updated)."""
    merged = dict(archive)
    added = updated = 0

    for key, row in incoming.items():
        if key not in merged:
            added += 1
        elif merged[key]["state"] != row["state"]:
            updated += 1
        merged[key] = row

    return merged, added, updated


def main():
    parser = argparse.ArgumentParser(
        description="Merge Home Assistant exports into a durable append-only archive"
    )
    parser.add_argument(
        "--input",
        "-i",
        nargs="+",
        required=True,
        help="One or more HA-shaped CSV exports to merge in",
    )
    parser.add_argument(
        "--archive",
        "-a",
        default=DEFAULT_ARCHIVE,
        help=f"Archive CSV path (default: {DEFAULT_ARCHIVE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress messages",
    )

    args = parser.parse_args()
    archive_path = Path(args.archive)

    try:
        archive = read_csv(archive_path)
    except (ValueError, OSError) as e:
        print(f"[ERROR] Failed to read archive: {e}", file=sys.stderr)
        return 1

    before = len(archive)
    total_added = total_updated = 0

    for src in args.input:
        try:
            incoming = read_csv(Path(src))
        except (ValueError, OSError) as e:
            print(f"[ERROR] Failed to read {src}: {e}", file=sys.stderr)
            return 1

        if not incoming:
            print(f"[WARN] {src}: no rows", file=sys.stderr)
            continue

        archive, added, updated = merge(archive, incoming)
        total_added += added
        total_updated += updated

        if not args.quiet:
            print(f"  {src}: {len(incoming)} rows → +{added} new, {updated} updated")

    if args.dry_run:
        print(f"[dry-run] {before} → {len(archive)} rows "
              f"(+{total_added} new, {total_updated} updated); nothing written")
        return 0

    try:
        write_csv(archive_path, archive)
    except OSError as e:
        print(f"[ERROR] Failed to write archive: {e}", file=sys.stderr)
        return 1

    if not args.quiet:
        times = [key[1] for key in archive]
        print(f"\n✓ Archive {archive_path}: {before} → {len(archive)} rows "
              f"(+{total_added} new, {total_updated} updated)")
        if times:
            print(f"  Range: {min(times)} → {max(times)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
