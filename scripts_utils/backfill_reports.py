#!/usr/bin/env python3
"""
backfill_reports.py — Recompute historical daily reports with the fixed harness.
================================================================================

The daily reports from 2026-07-13 to 2026-08-13 were produced by a measurement
harness with known defects (see docs_site/CHANGELOG.md, 2026-08-13): a
10-minute grid against hourly ground truth, an unclipped analysis window, a
row-based forward-fill limit, a replica reading the wrong sensor, and pressure
models that failed on import. Their numbers are superseded.

This script regenerates each of those reports from archived data with the
current harness, so the published history is measured the same way the present
is. It deliberately reuses the production pipeline — `run_analysis.py` for the
numbers and `daily_analysis.generate_report` for the markdown — rather than
reimplementing either; the only additions are a fixed window anchor and a
provenance note in the output.

Inputs (all committed, so the run is reproducible):
  data/archive/ha_hourly.csv     — HA long-term statistics, 2026-07-01 onward
  data/archive/om_backfill.json  — Open-Meteo archive, 2026-06-15 → 2026-08-13
  data/archive/ms_backfill.json  — Meteostat, same range

Differences from the original reports, stated once here:
  * Windows are anchored at 00:00 UTC of the day after the report date, not at
    the wall-clock moment the original cron fired. Deterministic and uniform.
  * Yandex snapshots are not reachable from this environment, so the Yandex
    columns and the Yandex ground-truth cross-check are absent.
  * HA history comes from long-term statistics (hourly means), not the live
    recorder, and begins 2026-07-01 (pressure 2026-07-12). Early 14d/28d
    windows therefore have partial HA coverage — the reports state it.

Usage:
  python scripts_utils/backfill_reports.py                 # full range
  python scripts_utils/backfill_reports.py --start 2026-08-01 --end 2026-08-03
"""

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts_utils import daily_analysis  # noqa: E402  (needs REPO on sys.path)

WINDOWS = (7, 14, 28)
HA_CSV = REPO / "data/archive/ha_hourly.csv"
OM_JSON = REPO / "data/archive/om_backfill.json"
MS_JSON = REPO / "data/archive/ms_backfill.json"

PROVENANCE = (
    "> **Recomputed {today} with the fixed measurement harness** "
    "(docs_site/CHANGELOG.md, 2026-08-13). This supersedes the report "
    "originally generated on this date, whose numbers were artifacts of the "
    "old harness. Windows are anchored at 00:00 UTC of the following day; "
    "Yandex data was not reachable at recompute time and is absent.\n"
)


def run_window(day: date, days: int, python: str) -> dict | None:
    """Run the analysis pipeline for one (date, window) pair; return its JSON."""
    window_end = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) \
        + timedelta(days=1)
    window_start = window_end - timedelta(days=days)

    out_dir = REPO / f"reports/daily/{day.isoformat()}/{days}d/backfill"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / "analysis_report.json"

    cmd = [
        python, str(REPO / "analysis/run_analysis.py"),
        "--ha-csv", str(HA_CSV),
        "--om-sources", str(OM_JSON),
        "--meteostat", str(MS_JSON),
        "--window-start", window_start.isoformat(),
        "--window-end", window_end.isoformat(),
        "--output", str(out_json),
        "--quiet",
    ]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"  ✗ {day} {days}d failed:\n{proc.stderr[-2000:]}", file=sys.stderr)
        return None
    with open(out_json) as f:
        return json.load(f)


def backfill_one(day: date, python: str) -> bool:
    results = {}
    for days in WINDOWS:
        results[days] = run_window(day, days, python)
        if results[days] is None:
            return False

    report_md = daily_analysis.generate_report(
        day.isoformat(), results[7], results[14], results[28])

    # Insert the provenance note right after the "**Generated:**" line, so the
    # report format otherwise stays byte-compatible with the daily pipeline's.
    note = PROVENANCE.format(today=date.today().isoformat())
    lines = report_md.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("**Generated:**"):
            lines.insert(i + 1, "")
            lines.insert(i + 2, note)
            break
    else:
        lines.insert(0, note)

    out_md = REPO / f"reports/{day.isoformat()}.md"
    out_md.write_text("\n".join(lines))
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recompute historical daily reports with the fixed harness")
    parser.add_argument("--start", default="2026-07-13",
                        help="First report date (default: 2026-07-13)")
    parser.add_argument("--end", default="2026-08-13",
                        help="Last report date (default: 2026-08-13)")
    parser.add_argument("--python", default=sys.executable,
                        help="Interpreter with pandas/numpy/sklearn")
    args = parser.parse_args()

    for path in (HA_CSV, OM_JSON, MS_JSON):
        if not path.exists():
            print(f"✗ Missing input: {path}", file=sys.stderr)
            return 1

    day = date.fromisoformat(args.start)
    last = date.fromisoformat(args.end)
    failed = []
    while day <= last:
        started = datetime.now()
        ok = backfill_one(day, args.python)
        took = (datetime.now() - started).total_seconds()
        print(f"{'✓' if ok else '✗'} {day}  ({took:.0f}s)", flush=True)
        if not ok:
            failed.append(day.isoformat())
        day += timedelta(days=1)

    if failed:
        print(f"\n✗ {len(failed)} dates failed: {', '.join(failed)}")
        return 1
    print("\n✓ Backfill complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
