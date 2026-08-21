#!/usr/bin/env python3
"""
run_full_analysis.py — Complete rain prediction analysis pipeline.
===================================================================

Collects all data sources and runs analysis in one go:
1. Fetch Home Assistant sensor history
2. Download Yandex Weather archive
3. Fetch Open-Meteo precipitation data
4. Fetch Meteostat data
5. Run analysis with all sources
6. Display results summary

Usage:
  python run_full_analysis.py --days 7 --output-dir reports/

Author: Karasik (AI assistant for Kickoman/rain-analysis)
"""

import argparse
import csv
import sys
import os
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone


def run_command(cmd: list, description: str, allow_fail: bool = False) -> bool:
    """Run a command and handle errors."""
    print(f"\n=== {description} ===")
    print(f"$ {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed: {e}", file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        if not allow_fail:
            sys.exit(1)
        return False
    except FileNotFoundError:
        print(f"✗ Command not found: {cmd[0]}", file=sys.stderr)
        if not allow_fail:
            sys.exit(1)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Complete rain prediction analysis pipeline"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days of history to fetch (default: 7)",
    )
    parser.add_argument(
        "--output-dir",
        default="reports",
        help="Output directory for reports and data (default: reports/)",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Data directory for intermediate files (default: data/)",
    )
    parser.add_argument(
        "--skip-plots",
        action="store_true",
        help="Skip generating PNG plots (faster)",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter to use (default: current)",
    )

    args = parser.parse_args()

    # Create directories
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) / timestamp
    data_dir = Path(args.data_dir)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("RAIN PREDICTION ANALYSIS PIPELINE")
    print("=" * 70)
    print(f"Timestamp: {timestamp}")
    print(f"Days: {args.days}")
    print(f"Output: {output_dir}")
    print(f"Data: {data_dir}")

    # Paths
    ha_csv = data_dir / f"ha_{timestamp}.csv"
    yandex_dir = data_dir / f"yandex_{timestamp}"
    om_json = data_dir / f"openmeteo_{timestamp}.json"
    report_json = output_dir / "analysis_report.json"

    # Step 1: Home Assistant
    run_command([
        args.python, "fetch_ha_data.py",
        "--days", str(args.days),
        "--output", str(ha_csv),
    ], "1/5: Fetching Home Assistant data")

    # Step 1b: Home Assistant long-term statistics + durable archive.
    #
    # The recorder purges after ~10 days, so a 14- or 28-day window fetched
    # from it alone is silently the same ~10-day window — the 2026-08-21
    # report shipped with its "14d" and "28d" columns byte-identical because
    # of exactly this. Statistics survive the purge; merging them (and the
    # committed archive, which reaches further back than either) restores the
    # window the report claims to cover. The recorder still contributes the
    # sensors statistics never carry: rain_probability and the spread sensor.
    stats_csv = data_dir / f"ha_stats_{timestamp}.csv"
    # Reach past the window: the pressure-anomaly models need a ~30-day
    # baseline *before* the window's first hour to be defined from day one.
    stats_days = max(args.days + 35, 45)
    stats_success = run_command([
        args.python, "fetch_ha_statistics.py",
        "--days", str(stats_days),
        "--output", str(stats_csv),
    ], "1b/5: Fetching HA long-term statistics", allow_fail=True)

    archive_csv = Path("data/archive/ha_hourly.csv")
    if stats_success and stats_csv.exists():
        run_command([
            args.python, "archive_ha_data.py",
            "--input", str(stats_csv),
            "--archive", str(archive_csv),
        ], "1c/5: Merging statistics into the durable archive", allow_fail=True)

    # Merge every HA history source into one CSV for the analysis. Exact
    # duplicate rows collapse; near-duplicates (an hourly mean next to raw
    # recorder samples) are fine — the grid resamples per column anyway.
    merged_rows = {}
    merged_order = []
    for source in (archive_csv, stats_csv, ha_csv):
        if not source.exists():
            continue
        with open(source, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                key = (row["entity_id"], row["last_changed"], row["state"])
                if key not in merged_rows:
                    merged_rows[key] = row
                    merged_order.append(row)
    if merged_order:
        merged_order.sort(key=lambda r: (r["last_changed"], r["entity_id"]))
        ha_merged = data_dir / f"ha_merged_{timestamp}.csv"
        with open(ha_merged, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["entity_id", "state", "last_changed"])
            writer.writeheader()
            writer.writerows(merged_order)
        print(f"    HA history merged: {len(merged_order)} rows "
              f"({'archive, ' if archive_csv.exists() else ''}statistics, recorder)")
        ha_csv = ha_merged

    # Step 2: Yandex Weather
    run_command([
        args.python, "fetch_yandex_archive.py",
        "--output", str(yandex_dir),
    ], "2/5: Downloading Yandex Weather archive")

    # Step 3: Open-Meteo
    om_success = run_command([
        args.python, "fetch_openmeteo.py",
        "--days", str(args.days),
        "--output", str(om_json),
    ], "3/5: Fetching Open-Meteo data", allow_fail=True)

    # Step 4: Meteostat
    ms_json = data_dir / f"meteostat_{timestamp}.json"
    ms_success = run_command([
        args.python, "fetch_meteostat.py",
        "--days", str(args.days),
        "--output", str(ms_json),
    ], "4/5: Fetching Meteostat data", allow_fail=True)

    if not om_success:
        print("\n⚠️  Open-Meteo fetch failed (network timeout?)")
        print("    Analysis will continue without Open-Meteo ground truth")
    
    if not ms_success:
        print("\n⚠️  Meteostat fetch failed")
        print("    Analysis will continue without pressure/precip data from Meteostat")

    # Step 5: Run analysis
    #
    # The window is passed explicitly: without it the grid spans the union of
    # every source's timespan, so the multi-day Yandex archive would stretch a
    # 7-day run into a mostly-empty 43-day grid.
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(days=args.days)

    analysis_cmd = [
        args.python, "run_analysis.py",
        "--ha-csv", str(ha_csv),
        "--yandex-dir", str(yandex_dir),
        "--window-start", window_start.isoformat(),
        "--window-end", window_end.isoformat(),
        "--output", str(report_json),
    ]
    
    if om_success and om_json.exists():
        analysis_cmd.extend(["--om-sources", str(om_json)])
    
    if ms_success and ms_json.exists():
        analysis_cmd.extend(["--meteostat", str(ms_json)])
    
    if not args.skip_plots:
        analysis_cmd.append("--plots")

    run_command(analysis_cmd, "5/5: Running analysis")

    # Step 6: Display summary
    print("\n" + "=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)

    if report_json.exists():
        with open(report_json) as f:
            report = json.load(f)
        
        # Extract key results
        meta = report.get("metadata", {})
        scores = report.get("scoring", {}).get("scores", {})
        best = report.get("scoring", {}).get("best_overall")
        
        print(f"\nData range: {meta.get('data_stats', {}).get('grid_start')} →")
        print(f"            {meta.get('data_stats', {}).get('grid_end')}")
        
        print("\nModel Performance (F1 scores):")
        for model, s in scores.items():
            f1 = s.get('f1')
            if f1 is not None:
                print(f"  {model:<20} F1={f1:.3f}  (P={s.get('precision', 0):.3f}, R={s.get('recall', 0):.3f})")
            else:
                print(f"  {model:<20} N/A")
        
        if best:
            print(f"\nBest overall (F-beta=2): {best['model']} @ {best['threshold']}%")
        
        print(f"\nFull report: {report_json}")
        
        # List plots if generated
        plots = list(output_dir.glob("*.png"))
        if plots:
            print(f"Plots: {', '.join(p.name for p in plots)}")
    
    print("\n✓ Pipeline complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
