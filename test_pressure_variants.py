#!/usr/bin/env python3
"""
test_pressure_variants.py — Compare pressure-aware model variants
===================================================================

Tests the 4 pressure model variants (A, B, C, D) against the baseline
pressure_aware model to see which approach works best.

Usage:
  python test_pressure_variants.py --days 30

Output: Markdown report with metrics comparison for each variant.

Created for issue #40
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import rainlib
from pressure_variants import PRESSURE_VARIANTS


def main():
    parser = argparse.ArgumentParser(
        description="Test pressure-aware model variants"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to analyze (default: 30)",
    )
    parser.add_argument(
        "--ha-csv",
        help="Path to Home Assistant CSV export (auto-detected if not specified)",
    )
    parser.add_argument(
        "--om-sources",
        help="Path to Open-Meteo JSON (auto-detected if not specified)",
    )
    parser.add_argument(
        "--meteostat",
        help="Path to Meteostat JSON (auto-detected if not specified)",
    )
    parser.add_argument(
        "--yandex-dir",
        default="data/yandex_archive",
        help="Path to Yandex archive directory",
    )
    parser.add_argument(
        "--output",
        help="Output markdown file (default: reports/pressure_variants_TIMESTAMP.md)",
    )

    args = parser.parse_args()

    # Auto-detect data files if not specified
    data_dir = Path("data")
    if not args.ha_csv:
        ha_files = sorted(data_dir.glob("ha_*.csv"))
        if ha_files:
            args.ha_csv = str(ha_files[-1])
            print(f"Auto-detected HA CSV: {args.ha_csv}")
        else:
            print("ERROR: No HA CSV found. Run fetch_ha_data.py first.")
            return 1

    if not args.om_sources:
        om_files = sorted(data_dir.glob("openmeteo_*.json"))
        if om_files:
            args.om_sources = str(om_files[-1])
            print(f"Auto-detected Open-Meteo: {args.om_sources}")

    if not args.meteostat:
        ms_files = sorted(data_dir.glob("meteostat_*.json"))
        if ms_files:
            args.meteostat = str(ms_files[-1])
            print(f"Auto-detected Meteostat: {args.meteostat}")

    # Load data
    print("\nLoading data...")
    ha_long = rainlib.load_ha_csv(args.ha_csv)
    
    entity_map = {
        "sensor.datchik_klimata_temperatura": "temp",
        "sensor.datchik_klimata_vlazhnost": "rh",
        "sensor.filtered_pressure": "pressure",
    }
    ha_wide = rainlib.ha_wide(ha_long, entity_map)
    
    yandex_archive = None
    if Path(args.yandex_dir).exists():
        yandex_archive = rainlib.load_yandex_archive(args.yandex_dir)
    
    om_data = None
    if args.om_sources and Path(args.om_sources).exists():
        om_data = rainlib.load_open_meteo(args.om_sources)
    
    ms_data = None
    if args.meteostat and Path(args.meteostat).exists():
        ms_data = rainlib.load_meteostat(args.meteostat)

    # Build unified grid
    print("Building unified time grid...")
    grid = rainlib.build_grid(
        ha_wide_df=ha_wide,
        om_df=om_data,
        yx_df=yandex_archive,
        ms_df=ms_data,
    )


    # Calculate spread and derivative
    grid["spread"] = rainlib.dew_point_spread(grid["temp"], grid["rh"])
    grid["spread_deriv"] = rainlib.derivative(grid["spread"], window="3h")
    
    # Get pressure series
    pressure = rainlib.build_pressure_series(
        grid,
        ha_pressure_col="pressure",
        ms_pres_col="ms_pres",
        yx_pressure_col="yx_pressure_mm",
    )

    # Ground truth
    if "om_precip" in grid.columns:
        ground_truth = (grid["om_precip"] > 0.0).astype(int)
    else:
        print("WARNING: No ground truth (Open-Meteo) available")
        ground_truth = None

    # Build context
    ctx = rainlib.ModelContext(
        spread=grid["spread"],
        spread_deriv=grid["spread_deriv"],
        pressure=pressure,
    )

    # Test all variants
    print("\nTesting model variants...")
    results = {}
    
    # Baseline: original pressure_aware
    print("  - pressure_aware (baseline)")
    pred = rainlib.model_pressure_aware(ctx)
    if ground_truth is not None:
        pred_aligned = pred.reindex(ground_truth.index)
        metrics = rainlib.confusion_at_threshold(pred_aligned, ground_truth, threshold=50)
        results["pressure_aware"] = metrics
    
    # Variants A, B, C, D
    for name, model_func in PRESSURE_VARIANTS.items():
        print(f"  - {name}")
        pred = model_func(ctx)
        if ground_truth is not None:
            metrics = rainlib.confusion_at_threshold(pred.reindex(ground_truth.index), ground_truth, threshold=50)
            results[name] = metrics

    # Generate report
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path("reports") / f"pressure_variants_{timestamp}.md"
    
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write markdown report
    with open(output_path, "w") as f:
        f.write(f"# Pressure Model Variants Comparison\n\n")
        f.write(f"**Date:** {timestamp}  \n")
        f.write(f"**Analysis period:** {args.days} days  \n")
        
        if pressure is not None:
            pressure_start = pressure.first_valid_index()
            f.write(f"**Pressure data available from:** {pressure_start}  \n")
        
        f.write("\n## Variants Tested\n\n")
        f.write("- **A (absolute):** Pressure trend + absolute pressure bonus\n")
        f.write("- **B (long_window):** 12h window instead of 3h\n")
        f.write("- **C (lagged):** 6h lagged pressure\n")
        f.write("- **D (combined):** All techniques combined\n")
        
        f.write("\n## Results\n\n")
        f.write("| Model | F1 | Precision | Recall | TP | FP | FN |\n")
        f.write("|-------|----|-----------|----|----|----|----|\n")
        
        for name, m in results.items():
            f.write(f"| {name} | {m['f1']:.3f} | {m['precision']:.3f} | {m['recall']:.3f} | ")
            f.write(f"{m['tp']} | {m['fp']} | {m['fn']} |\n")
        
        f.write("\n## Analysis\n\n")
        
        # Find best model
        if results:
            best_name = max(results.keys(), key=lambda k: results[k]['f1'])
            best_f1 = results[best_name]['f1']
            baseline_f1 = results.get('pressure_aware', {}).get('f1', 0)
            
            f.write(f"**Best model:** {best_name} (F1={best_f1:.3f})  \n")
            f.write(f"**Baseline:** pressure_aware (F1={baseline_f1:.3f})  \n")
            
            improvement = best_f1 - baseline_f1
            if improvement > 0.01:
                f.write(f"**Improvement:** +{improvement:.3f} ({improvement/baseline_f1*100:.1f}%)  \n")
            elif improvement < -0.01:
                f.write(f"**Change:** {improvement:.3f} ({improvement/baseline_f1*100:.1f}%)  \n")
            else:
                f.write(f"**Change:** Negligible ({improvement:.3f})  \n")
        
        f.write("\n## Observations\n\n")
        f.write("_Add manual observations here after reviewing the results._\n")
        f.write("\n---\n")
        f.write(f"Generated by test_pressure_variants.py for issue #40\n")

    print(f"\n✓ Report written to: {output_path}")
    
    # Print summary to console
    print("\n" + "="*60)
    print("RESULTS SUMMARY")
    print("="*60)
    for name, m in results.items():
        print(f"{name:25} F1={m['f1']:.3f}  P={m['precision']:.3f}  R={m['recall']:.3f}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
