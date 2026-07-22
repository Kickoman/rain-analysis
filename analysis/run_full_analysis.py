#!/usr/bin/env python3
"""
run_full_analysis.py — Complete rain prediction analysis pipeline.
===================================================================

Collects all data sources and runs analysis in one go:
1. Fetch Home Assistant sensor history
2. Download Yandex Weather archive
3. Fetch Open-Meteo precipitation data
4. Run analysis with all sources
5. Display results summary

Usage:
  python run_full_analysis.py --days 7 --output-dir reports/

Author: Karasik (AI assistant for Kickoman/rain-analysis)
"""

import argparse
import sys
import os
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone


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
    ], "1/4: Fetching Home Assistant data")

    # Step 2: Yandex Weather
    run_command([
        args.python, "fetch_yandex_archive.py",
        "--output", str(yandex_dir),
    ], "2/4: Downloading Yandex Weather archive")

    # Step 3: Open-Meteo
    om_success = run_command([
        args.python, "fetch_openmeteo.py",
        "--days", str(args.days),
        "--output", str(om_json),
    ], "3/4: Fetching Open-Meteo data", allow_fail=True)

    # Step 4: Meteostat
    ms_json = data_dir / f"meteostat_{timestamp}.json"
    ms_success = run_command([
        args.python, "fetch_meteostat.py",
        "--days", str(args.days),
        "--output", str(ms_json),
    ], "4/4: Fetching Meteostat data", allow_fail=True)

    if not om_success:
        print("\n⚠️  Open-Meteo fetch failed (network timeout?)")
        print("    Analysis will continue without Open-Meteo ground truth")
    
    if not ms_success:
        print("\n⚠️  Meteostat fetch failed")
        print("    Analysis will continue without pressure/precip data from Meteostat")

    # Step 4: Run analysis
    analysis_cmd = [
        args.python, "run_analysis.py",
        "--ha-csv", str(ha_csv),
        "--yandex-dir", str(yandex_dir),
        "--output", str(report_json),
    ]
    
    if om_success and om_json.exists():
        analysis_cmd.extend(["--om-sources", str(om_json)])
    
    if ms_success and ms_json.exists():
        analysis_cmd.extend(["--meteostat", str(ms_json)])
    
    if not args.skip_plots:
        analysis_cmd.append("--plots")

    run_command(analysis_cmd, "Running analysis")

    # Step 5: Display summary
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
