#!/usr/bin/env python3
"""
compare_pressure_sources.py — Compare pressure-aware models on isolated sources
==============================================================================

Tests pressure-aware models separately on each isolated pressure source:
- Home Assistant sensors only
- Meteostat only
- Yandex archive only

This ensures sources are not mixed, as requested in issue #52.

Usage:
  python compare_pressure_sources.py --days 30

Output: Markdown report comparing model performance across isolated sources.

Updated for issue #52
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import rainlib
from pressure_variants import PRESSURE_VARIANTS


def run_models_with_pressure_source(grid, ground_truth, pressure_series, source_name):
    """Test all model variants with a specific pressure source.
    
    Returns dict of {model_name: metrics}
    """
    if pressure_series is None or pressure_series.dropna().empty:
        print(f"    WARNING: No {source_name} pressure data available")
        return {}
    
    # Build context with this pressure source
    ctx = rainlib.ModelContext(
        spread=grid["spread"],
        spread_deriv=grid["spread_deriv"],
        pressure=pressure_series,
    )
    
    results = {}
    
    # Baseline: pressure_aware
    print(f"    - pressure_aware (baseline)")
    pred = rainlib.model_pressure_aware(ctx)
    if ground_truth is not None:
        pred_aligned = pred.reindex(ground_truth.index)
        metrics = rainlib.confusion_at_threshold(pred_aligned, ground_truth, threshold=50)
        results["pressure_aware"] = metrics
    
    # Variants A, B, C, D
    for name, model_func in PRESSURE_VARIANTS.items():
        print(f"    - {name}")
        pred = model_func(ctx)
        if ground_truth is not None:
            pred_aligned = pred.reindex(ground_truth.index)
            metrics = rainlib.confusion_at_threshold(pred_aligned, ground_truth, threshold=50)
            results[name] = metrics
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Test pressure-aware model variants on isolated sources"
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
    
    # Get ISOLATED pressure series for each source
    print("\nExtracting isolated pressure sources...")
    pressure_ha = rainlib.build_pressure_series_ha(grid)
    pressure_ms = rainlib.build_pressure_series_meteostat(grid)
    pressure_yx = rainlib.build_pressure_series_yandex(grid)
    
    if pressure_ha is not None:
        print(f"  ✓ HA pressure: {pressure_ha.notna().sum()} samples")
    if pressure_ms is not None:
        print(f"  ✓ Meteostat pressure: {pressure_ms.notna().sum()} samples")
    if pressure_yx is not None:
        print(f"  ✓ Yandex pressure: {pressure_yx.notna().sum()} samples")

    # Ground truth
    if "om_precip" in grid.columns:
        ground_truth = (grid["om_precip"] > 0.0).astype(int)
        print(f"  ✓ Ground truth: {len(ground_truth)} samples")
    else:
        print("WARNING: No ground truth (Open-Meteo) available")
        ground_truth = None

    # Test models on each isolated source
    print("\nTesting models on isolated sources...")
    all_results = {}
    
    if pressure_ha is not None:
        print("  [Home Assistant pressure]")
        all_results["HA"] = run_models_with_pressure_source(grid, ground_truth, pressure_ha, "HA")
    
    if pressure_ms is not None:
        print("  [Meteostat pressure]")
        all_results["Meteostat"] = run_models_with_pressure_source(grid, ground_truth, pressure_ms, "Meteostat")
    
    if pressure_yx is not None:
        print("  [Yandex pressure]")
        all_results["Yandex"] = run_models_with_pressure_source(grid, ground_truth, pressure_yx, "Yandex")

    # Generate report
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path("reports") / f"pressure_variants_{timestamp}.md"
    
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write markdown report
    with open(output_path, "w") as f:
        f.write(f"# Pressure Model Variants — Isolated Sources Comparison\n\n")
        f.write(f"**Date:** {timestamp}  \n")
        f.write(f"**Analysis period:** {args.days} days  \n")
        f.write(f"**Issue:** #52 — Test models on isolated pressure sources (no mixing)  \n\n")
        
        f.write("## Methodology\n\n")
        f.write("Models are tested separately on each isolated pressure source:\n\n")
        f.write("- **HA (Home Assistant):** Production sensor only — no fallbacks\n")
        f.write("- **Meteostat:** Historical weather station data only\n")
        f.write("- **Yandex:** Yandex Weather archive only\n\n")
        f.write("This ensures no mixing of sources, as production will use HA sensors exclusively.\n\n")
        
        f.write("## Model Variants\n\n")
        f.write("- **pressure_aware (baseline):** Standard pressure-aware model\n")
        f.write("- **A (absolute):** Pressure trend + absolute pressure bonus\n")
        f.write("- **B (long_window):** 12h window instead of 3h\n")
        f.write("- **C (lagged):** 6h lagged pressure\n")
        f.write("- **D (combined):** All techniques combined\n\n")
        
        # Results for each source
        for source_name, results in all_results.items():
            f.write(f"## Results: {source_name} Pressure\n\n")
            
            if not results:
                f.write("*No data available for this source*\n\n")
                continue
            
            f.write("| Model | F1 | Precision | Recall | TP | FP | FN |\n")
            f.write("|-------|----|-----------|----|----|----|----|\n")
            
            for model_name, m in results.items():
                f.write(f"| {model_name} | {m['f1']:.3f} | {m['precision']:.3f} | {m['recall']:.3f} | ")
                f.write(f"{m['tp']} | {m['fp']} | {m['fn']} |\n")
            
            # Find best model for this source
            best_name = max(results.keys(), key=lambda k: results[k]['f1'])
            best_f1 = results[best_name]['f1']
            baseline_f1 = results.get('pressure_aware', {}).get('f1', 0)
            
            f.write(f"\n**Best model for {source_name}:** {best_name} (F1={best_f1:.3f})  \n")
            if baseline_f1 > 0:
                improvement = best_f1 - baseline_f1
                f.write(f"**Baseline:** pressure_aware (F1={baseline_f1:.3f})  \n")
                if improvement > 0.01:
                    f.write(f"**Improvement:** +{improvement:.3f} ({improvement/baseline_f1*100:.1f}%)  \n")
                elif improvement < -0.01:
                    f.write(f"**Change:** {improvement:.3f} ({improvement/baseline_f1*100:.1f}%)  \n")
                else:
                    f.write(f"**Change:** Negligible ({improvement:.3f})  \n")
            f.write("\n")
        
        f.write("## Cross-Source Comparison\n\n")
        f.write("Comparing baseline model (pressure_aware) across sources:\n\n")
        f.write("| Source | F1 | Precision | Recall | Sample Count |\n")
        f.write("|--------|----|-----------|----|-------------|\n")
        
        for source_name in ["HA", "Meteostat", "Yandex"]:
            if source_name in all_results and "pressure_aware" in all_results[source_name]:
                m = all_results[source_name]["pressure_aware"]
                samples = m['tp'] + m['fp'] + m['fn'] + m.get('tn', 0)
                f.write(f"| {source_name} | {m['f1']:.3f} | {m['precision']:.3f} | {m['recall']:.3f} | {samples} |\n")
        
        f.write(f"\n---\n")
        f.write(f"Generated by compare_pressure_sources.py for issue #52\n")

    print(f"\n✓ Report written to: {output_path}")
    
    # Print summary to console
    print("\n" + "="*70)
    print("RESULTS SUMMARY")
    print("="*70)
    
    for source_name, results in all_results.items():
        if results:
            print(f"\n{source_name} Pressure:")
            for model_name, m in results.items():
                print(f"  {model_name:25} F1={m['f1']:.3f}  P={m['precision']:.3f}  R={m['recall']:.3f}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
