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

It has since served a second purpose: filling the gap left when the runner
that generated the daily reports stopped after 2026-08-22. There the local
sensor history comes from the backend (see pull_measurements.py) rather than
from Home Assistant, which is why every input is an argument.

Inputs (defaults are the committed archive, so a default run is reproducible):
  --ha-csv      data/archive/ha_hourly.csv     — HA history, 2026-07-01 onward
  --om-sources  data/archive/om_backfill.json  — Open-Meteo, 2026-06-15 onward
  --meteostat   data/archive/ms_backfill.json  — Meteostat, same range
  --yandex-dir  none by default — the archive is not always reachable

Pass ONE Open-Meteo source unless the files genuinely do not overlap: on
overlapping hours the last source wins, which mixes two different series
(the ERA5 archive and the forecast past-days series disagree by ~3x on rain
hours) into one ground truth.

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
  python scripts_utils/backfill_reports.py --start 2026-08-23 --end 2026-09-03 \
      --om-sources data/archive/om_backfill_forecast.json \
      --yandex-dir data/yandex_archive --provenance "> ..."
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
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


@dataclass
class Inputs:
    """The data files one backfill run reads. Defaults are the committed archive."""

    ha_csv: Path = HA_CSV
    om_sources: tuple[Path, ...] = (OM_JSON,)
    meteostat: Path = MS_JSON
    yandex_dir: Path | None = None

    def paths(self):
        required = [self.ha_csv, *self.om_sources, self.meteostat]
        return required + ([self.yandex_dir] if self.yandex_dir else [])


def run_window(day: date, days: int, python: str, inputs: Inputs) -> dict | None:
    """Run the analysis pipeline for one (date, window) pair; return its JSON."""
    window_end = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) \
        + timedelta(days=1)
    window_start = window_end - timedelta(days=days)

    out_dir = REPO / f"reports/daily/{day.isoformat()}/{days}d/backfill"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / "analysis_report.json"

    cmd = [
        python, str(REPO / "analysis/run_analysis.py"),
        "--ha-csv", str(inputs.ha_csv),
        "--om-sources", *[str(src) for src in inputs.om_sources],
        "--meteostat", str(inputs.meteostat),
        "--window-start", window_start.isoformat(),
        "--window-end", window_end.isoformat(),
        "--output", str(out_json),
        "--quiet",
    ]
    if inputs.yandex_dir:
        cmd += ["--yandex-dir", str(inputs.yandex_dir)]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"  ✗ {day} {days}d failed:\n{proc.stderr[-2000:]}", file=sys.stderr)
        return None
    with open(out_json) as f:
        return json.load(f)


def backfill_one(day: date, python: str, inputs: Inputs, provenance: str) -> bool:
    results = {}
    for days in WINDOWS:
        results[days] = run_window(day, days, python, inputs)
        if results[days] is None:
            return False

    report_md = daily_analysis.generate_report(
        day.isoformat(), results[7], results[14], results[28])

    # Insert the provenance note right after the "**Generated:**" line, so the
    # report format otherwise stays byte-compatible with the daily pipeline's.
    note = provenance.format(today=date.today().isoformat())
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
    parser.add_argument("--ha-csv", type=Path, default=HA_CSV,
                        help="HA history CSV (entity_id,state,last_changed)")
    parser.add_argument("--om-sources", type=Path, nargs="+", default=[OM_JSON],
                        help="Open-Meteo JSON files; on overlap the last one wins")
    parser.add_argument("--meteostat", type=Path, default=MS_JSON,
                        help="Meteostat JSON file")
    parser.add_argument("--yandex-dir", type=Path, default=None,
                        help="Directory of Yandex snapshots (default: none, "
                             "the archive is not always reachable)")
    parser.add_argument("--provenance", default=PROVENANCE,
                        help="Provenance note inserted after the Generated line; "
                             "{today} is substituted")
    args = parser.parse_args()

    inputs = Inputs(ha_csv=args.ha_csv, om_sources=tuple(args.om_sources),
                    meteostat=args.meteostat, yandex_dir=args.yandex_dir)

    for path in inputs.paths():
        if not path.exists():
            print(f"✗ Missing input: {path}", file=sys.stderr)
            return 1

    day = date.fromisoformat(args.start)
    last = date.fromisoformat(args.end)
    failed = []
    while day <= last:
        started = datetime.now()
        ok = backfill_one(day, args.python, inputs, args.provenance)
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
