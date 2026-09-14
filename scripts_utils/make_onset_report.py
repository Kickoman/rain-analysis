#!/usr/bin/env python3
"""
make_onset_report.py — produce one daily report, onset-first, from the archive.
==============================================================================

Replaces the three-window daily pipeline (7d/14d/28d) with a single run over
the **whole record**. The reason is arithmetic: a 7-day window holds three or
four rain onsets, and "best model" picked from three events is a coin toss
dressed as a ranking. The full record holds tens of them, and the report says
how wide the error bars still are.

What it does:
  1. run_analysis.py over record-start → the day after the report date,
     dumping the hourly grid;
  2. re-reads that grid to describe the report day itself;
  3. renders the compact report (scripts_utils/onset_report.py);
  4. optionally POSTs it to the backend reports API.

Usage:
  python scripts_utils/make_onset_report.py --date 2026-09-14
  python scripts_utils/make_onset_report.py --date 2026-09-14 --push
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts_utils import onset_report  # noqa: E402

# The record starts where the Open-Meteo forecast series does; earlier hours
# have ground truth from the ERA5 archive, which reports ~3x as many rain hours
# and would make the two halves of the window incomparable.
DEFAULT_START = "2026-07-18T00:00:00+00:00"


def run_analysis(day: date, python: str, inputs: dict, out_dir: Path) -> tuple[dict, Path]:
    window_end = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / "analysis_report.json"
    out_grid = out_dir / "grid.csv"

    cmd = [
        python, str(REPO / "analysis/run_analysis.py"),
        "--ha-csv", inputs["ha_csv"],
        "--om-sources", *inputs["om_sources"],
        "--meteostat", inputs["meteostat"],
        "--window-start", inputs["start"],
        "--window-end", window_end.isoformat(),
        "--output", str(out_json),
        "--dump-grid", str(out_grid),
        "--quiet",
    ]
    if inputs.get("yandex_dir"):
        cmd += ["--yandex-dir", inputs["yandex_dir"]]

    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"run_analysis failed for {day}:\n{proc.stderr[-2000:]}")
    with open(out_json) as f:
        return json.load(f), out_grid


def day_rows(grid_csv: Path, day: date, front: dict) -> list[dict]:
    """The report day's hours, flagged with onsets and with each model's alerts.

    Read back from the dumped grid rather than recomputed, so the narrative
    cannot drift from the numbers in the table above it.
    """
    scores = front.get("scores") or {}
    proven = [n for n in (front.get("proven_models") or [])
              if n not in onset_report.BASELINES]
    thresholds = {n: ((scores.get(n) or {}).get("events") or {}).get("threshold")
                  for n in proven}
    # `ha_live_replica` is column model_ha_live; the deployed sensor is its own column.
    column = {n: ("ha_rain_prob" if n == "ha_live_actual"
                  else "model_ha_live" if n == "ha_live_replica"
                  else f"model_{n}") for n in proven}

    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    rows, prev_rain = [], []
    with open(grid_csv) as f:
        for raw in csv.DictReader(f):
            ts = datetime.fromisoformat(raw["time"])
            rain = raw.get("rain_truth")
            rain = float(rain) if rain not in (None, "") else None
            prev_rain.append(rain)
            if not (start <= ts < end):
                continue
            # Onset: rain now after three known-dry hours, the same rule the
            # scoring uses.
            lookback = prev_rain[-4:-1]
            is_onset = (rain == 1.0 and len(lookback) == 3
                        and all(v == 0.0 for v in lookback))
            row = {"time": ts, "is_onset": is_onset}
            for name, col in column.items():
                thr = thresholds.get(name)
                value = raw.get(col)
                value = float(value) if value not in (None, "") else None
                row[f"alert_{name}"] = (value is not None and thr is not None
                                        and value >= thr and rain == 0.0)
                row[f"value_{name}"] = value
            rows.append(row)

    # Was there an alert in the horizon *before* each onset?
    horizon = int(front.get("horizon_hours") or 3)
    by_time = {r["time"]: r for r in rows}
    for r in rows:
        if not r["is_onset"]:
            continue
        for name in column:
            r[f"warned_{name}"] = any(
                by_time.get(r["time"] - timedelta(hours=k), {}).get(f"alert_{name}")
                for k in range(1, horizon + 1)
            )
    return rows


def push_to_backend(day: date, markdown: str, results: dict, url: str, key: str) -> None:
    import requests
    sys.path.insert(0, str(REPO / "scripts_utils"))
    from migrate_reports_to_backend import build_content

    payload = {
        "report_date": day.isoformat(),
        "content": build_content(markdown),
        "meta": {"source_markdown": markdown, "generator": "make_onset_report.py"},
    }
    r = requests.post(url.rstrip("/") + "/api/v1/reports", json=payload,
                      headers={"X-API-Key": key}, timeout=60)
    r.raise_for_status()
    print(f"  pushed to backend: {r.json().get('action')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--date", help="Report date YYYY-MM-DD (default: yesterday UTC)")
    parser.add_argument("--through", help="Render every date from --date to this one, inclusive")
    parser.add_argument("--start", default=DEFAULT_START, help="Record start")
    parser.add_argument("--ha-csv", default=str(REPO / "data/archive/ha_hourly.csv"))
    parser.add_argument("--om-sources", nargs="+",
                        default=[str(REPO / "data/archive/om_backfill_forecast.json")])
    parser.add_argument("--meteostat", default=str(REPO / "data/archive/ms_backfill.json"))
    parser.add_argument("--yandex-dir", default=None)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output-dir", default=str(REPO / "reports"))
    parser.add_argument("--run-dir", default=None,
                        help="Where the JSON and grid land (default reports/daily/<date>/full)")
    parser.add_argument("--push", action="store_true", help="POST the report to the backend")
    parser.add_argument("--backend-url", default=os.environ.get("RAIN_BACKEND_URL"))
    parser.add_argument("--backend-key", default=os.environ.get("RAIN_BACKEND_KEY"))
    parser.add_argument("--provenance", default=None,
                        help="Note inserted under the Generated line")
    args = parser.parse_args()

    first = (date.fromisoformat(args.date) if args.date
             else (datetime.now(timezone.utc) - timedelta(days=1)).date())
    last = date.fromisoformat(args.through) if args.through else first
    if last < first:
        raise SystemExit("--through is before --date")

    inputs = {
        "ha_csv": args.ha_csv, "om_sources": args.om_sources,
        "meteostat": args.meteostat, "yandex_dir": args.yandex_dir,
        "start": args.start,
    }

    failures = 0
    day = first
    while day <= last:
        try:
            render_one(day, args, inputs)
        except SystemExit as exc:            # one bad day must not sink the range
            print(f"  ✗ {day}: {exc}", file=sys.stderr)
            failures += 1
        day += timedelta(days=1)
    return 1 if failures else 0


def render_one(day: date, args, inputs: dict) -> None:
    run_dir = Path(args.run_dir) if args.run_dir else REPO / f"reports/daily/{day}/full"

    results, grid_csv = run_analysis(day, args.python, inputs, run_dir)
    front = (results.get("scoring") or {}).get("front_target") or {}
    rows = day_rows(grid_csv, day, front)
    markdown = onset_report.generate_report(day.isoformat(), results, rows)

    if args.provenance:
        note = args.provenance.format(today=date.today().isoformat())
        lines = markdown.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("**Generated:**"):
                lines.insert(i + 1, "")
                lines.insert(i + 2, note)
                break
        markdown = "\n".join(lines)

    out_md = Path(args.output_dir) / f"{day}.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(markdown, encoding="utf-8")
    print(f"✓ {out_md}  ({len(markdown.splitlines())} lines, "
          f"{front.get('n_onsets')} onsets over {front.get('window_days')} d)")

    if args.push:
        if not (args.backend_url and args.backend_key):
            raise SystemExit("--push needs RAIN_BACKEND_URL and RAIN_BACKEND_KEY")
        push_to_backend(day, markdown, results, args.backend_url, args.backend_key)


if __name__ == "__main__":
    sys.exit(main())
