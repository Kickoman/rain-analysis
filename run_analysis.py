#!/usr/bin/env python3
"""
run_analysis.py — Automated CLI analysis for rain-prediction models.
======================================================================

Drop-in replacement for running rain_analysis.ipynb without Jupyter.
Produces:
  - A JSON report with all scores, sweeps, and recommendations (LLM-friendly)
  - A human-readable text summary
  - Optional PNG plots (when --plots is passed or matplotlib is importable)

Designed to stay in sync with the notebook:
  - Same functions from rainlib.py
  - Same computation pipeline (§1 → §10 of the notebook)
  - Just automated + machine-readable output

Usage:
  python run_analysis.py \\
    --ha-csv /path/to/ha_full.csv \\
    --om-sources /path/to/om.json \\
    --yandex-dir /path/to/yandex_archive/ \\
    --output report.json \\
    --plots          # optional: save PNG plots

Author: Karasik (AI assistant for Kickoman/rain-analysis)
"""

from __future__ import annotations

import argparse
import json
import sys
import os
import itertools
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

# Use rainlib — no reinvention
import rainlib as rl
from rainlib import ModelParams, MODELS


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class AnalysisConfig:
    """All inputs and knobs for one analysis run."""
    ha_csv: str = ""
    om_sources: list[str] = field(default_factory=list)
    yandex_dir: Optional[str] = None

    ha_entities: dict = field(default_factory=lambda: {
        "sensor.datchik_klimata_temperatura": "temp",
        "sensor.datchik_klimata_vlazhnost": "rh",
        "sensor.rain_probability": "ha_rain_prob",
    })

    grid_freq: str = "10min"
    rain_threshold_mm: float = 0.1
    decision_threshold: float = 50.0
    deriv_window: str = "3h"

    # Model defaults (baseline)
    model_params: dict = field(default_factory=lambda: asdict(ModelParams()))

    # Grid search space for parameter tuning
    param_grid: dict = field(default_factory=lambda: {
        "proximity_divisor": [5, 6, 7, 8],
        "hysteresis_decay": [0.2, 0.3, 0.5],
        "trend_gain": [15, 20, 30],
    })

    # F-beta recommendations to compute
    betas: list[float] = field(default_factory=lambda: [0.5, 1.0, 2.0])

    output_dir: str = "."


# ---------------------------------------------------------------------------
# Analysis pipeline
# ---------------------------------------------------------------------------

def load_data(config: AnalysisConfig) -> pd.DataFrame:
    """§1-§2: Load & align everything onto one grid."""
    # Local sensors
    ha_long = rl.load_ha_csv(config.ha_csv)
    ha = rl.ha_wide(ha_long, config.ha_entities)

    # Open-meteo
    om_frames = [rl.load_open_meteo(src) for src in config.om_sources]
    om = pd.concat(om_frames).sort_index() if om_frames else pd.DataFrame()
    if not om.empty:
        om = om[~om.index.duplicated(keep="last")]

    # Yandex
    yx = rl.load_yandex_archive(config.yandex_dir) if config.yandex_dir else pd.DataFrame()

    grid = rl.build_grid(ha, om, yx, freq=config.grid_freq)

    stats = {
        "ha_rows": len(ha_long),
        "ha_cols": list(ha.columns),
        "om_hours": len(om),
        "om_cols": list(om.columns) if not om.empty else [],
        "yandex_snapshots": len(yx),
        "yandex_cols": list(yx.columns) if not yx.empty else [],
        "grid_shape": grid.shape,
        "grid_start": str(grid.index.min()),
        "grid_end": str(grid.index.max()),
    }

    return grid, stats


def compute_features(grid: pd.DataFrame, config: AnalysisConfig) -> pd.DataFrame:
    """§3: Compute physical features (dew point, spread, derivative)."""
    grid = grid.copy()
    grid["dew_point"] = rl.dew_point(grid["temp"], grid["rh"])
    grid["spread"] = rl.dew_point_spread(grid["temp"], grid["rh"])
    grid["abs_humidity"] = rl.absolute_humidity(grid["temp"], grid["rh"])
    grid["humidex"] = rl.humidex(grid["temp"], grid["dew_point"])
    grid["spread_deriv"] = rl.derivative(grid["spread"], window=config.deriv_window)
    return grid


def label_ground_truth(grid: pd.DataFrame, config: AnalysisConfig) -> tuple:
    """§4: Create rain_truth label and return rain-hour summary."""
    grid = grid.copy()
    grid["rain_truth"] = rl.label_rain(grid, "om_precip", config.rain_threshold_mm)

    rain_hours = (
        grid[grid["rain_truth"] == 1]
        .resample("1h")
        .last()
        .dropna(subset=["rain_truth"])
    )

    rain_summary = []
    om_precip_col = "om_precip"
    if om_precip_col in rain_hours.columns:
        for idx, row in rain_hours.iterrows():
            val = row.get(om_precip_col)
            if val is not None and not (isinstance(val, float) and np.isnan(val)):
                rain_summary.append({
                    "time": str(idx),
                    "precip_mm": float(val),
                })

    stats = {
        "total_rain_hours": len(rain_hours),
        "total_rain_mm": float(rain_hours.get(om_precip_col, pd.Series(dtype=float)).sum())
        if om_precip_col in rain_hours.columns else None,
        "rain_hours": rain_summary,
    }

    return grid, stats


def run_models(grid: pd.DataFrame, config: AnalysisConfig) -> tuple:
    """§5: Run all candidate models over the grid."""
    grid = grid.copy()

    params = ModelParams(**config.model_params)

    model_stats = {}
    for name in MODELS:
        col = f"model_{name}"
        grid[col] = MODELS[name](grid["spread"], grid["spread_deriv"], params)
        model_stats[name] = {
            "mean": float(grid[col].mean()),
            "std": float(grid[col].std()),
            "min": float(grid[col].min()),
            "max": float(grid[col].max()),
            "median": float(grid[col].median()),
            "count": int(grid[col].notna().sum()),
        }

    # HA live value stats
    ha_col = "ha_rain_prob"
    if ha_col in grid.columns:
        model_stats["ha_live"] = {
            "mean": float(grid[ha_col].mean()),
            "std": float(grid[ha_col].std()),
            "min": float(grid[ha_col].min()),
            "max": float(grid[ha_col].max()),
            "median": float(grid[ha_col].median()),
            "count": int(grid[ha_col].notna().sum()),
        }

    return grid, model_stats


def score_models(grid: pd.DataFrame, config: AnalysisConfig) -> dict:
    """§6-§7: Score all models + threshold sweep + F-beta recommendations."""
    model_cols = [f"model_{n}" for n in MODELS]
    if "ha_rain_prob" in grid.columns:
        model_cols.append("ha_rain_prob")

    scores = {}
    threshold_sweeps = {}
    fbeta_recs = {}
    best_overall = None

    for col in model_cols:
        # Basic confusion matrix at decision threshold
        c = rl.confusion_at_threshold(grid[col], grid["rain_truth"], config.decision_threshold)
        lt = rl.lead_time(grid[col], grid["rain_truth"], config.decision_threshold)

        display_name = col.replace("model_", "").replace("ha_rain_prob", "ha_live")

        scores[display_name] = {
            "precision": c["precision"] if not (isinstance(c["precision"], float) and np.isnan(c["precision"])) else None,
            "recall": c["recall"] if not (isinstance(c["recall"], float) and np.isnan(c["recall"])) else None,
            "f1": c["f1"] if not (isinstance(c["f1"], float) and np.isnan(c["f1"])) else None,
            "tp": c["tp"],
            "fp": c["fp"],
            "fn": c["fn"],
            "tn": c["tn"],
            "n_samples": c["n"],
            "lead_time_seconds": float(lt.total_seconds()) if lt is not None else None,
        }

        # Threshold sweep
        sw = rl.sweep_threshold(grid[col], grid["rain_truth"])
        threshold_sweeps[display_name] = [
            {
                "threshold": int(idx),
                "precision": float(row["precision"]) if not np.isnan(row["precision"]) else None,
                "recall": float(row["recall"]) if not np.isnan(row["recall"]) else None,
                "f1": float(row["f1"]) if not np.isnan(row["f1"]) else None,
            }
            for idx, row in sw.iterrows()
        ]

        # F-beta recommendations
        recs_for_model = {}
        for beta in config.betas:
            rec = rl.recommend_threshold(grid[col], grid["rain_truth"], beta=beta)
            recs_for_model[f"beta_{beta}"] = {
                "best_threshold": rec["best_threshold"],
                "precision": rec["precision"],
                "recall": rec["recall"],
                "fbeta": rec["fbeta"],
            }

            # Track best overall F-beta (beta=2, conservative)
            if beta == 2.0 and rec["fbeta"] is not None:
                if best_overall is None or rec["fbeta"] > best_overall["fbeta"]:
                    best_overall = {
                        "model": display_name,
                        "threshold": rec["best_threshold"],
                        "fbeta": rec["fbeta"],
                    }

        fbeta_recs[display_name] = recs_for_model

    return {
        "scores": scores,
        "threshold_sweeps": threshold_sweeps,
        "fbeta_recommendations": fbeta_recs,
        "best_overall": best_overall,
    }


def param_tuning(grid: pd.DataFrame, config: AnalysisConfig) -> dict:
    """§10: Grid search over ModelParams."""
    results = []
    keys = list(config.param_grid)

    for combo in itertools.product(*config.param_grid.values()):
        kw = dict(zip(keys, combo))
        p = ModelParams(**kw)
        pred = rl.model_tuned(grid["spread"], grid["spread_deriv"], p)
        c = rl.confusion_at_threshold(pred, grid["rain_truth"], config.decision_threshold)
        results.append({
            **kw,
            "precision": c["precision"] if not np.isnan(c["precision"]) else None,
            "recall": c["recall"] if not np.isnan(c["recall"]) else None,
            "f1": c["f1"] if not np.isnan(c["f1"]) else None,
        })

    # Sort by F1 descending
    results.sort(key=lambda r: r["f1"] if r["f1"] is not None else -1, reverse=True)

    top_n = 15
    return {
        "total_combinations": len(results),
        "best_params": results[0] if results else None,
        f"top_{top_n}": results[:top_n],
    }


def cross_check(grid: pd.DataFrame) -> dict:
    """§9: Compare Yandex vs open-meteo vs HA data availability and overlap."""
    cmp = grid.resample("1h").last()

    sources = {}
    for col in ["temp", "rh", "om_temp", "om_rh", "yx_temp", "yx_humidity",
                 "ha_rain_prob", "om_precip", "yx_prec_prob", "yx_condition"]:
        if col in cmp.columns:
            series = cmp[col].dropna()
            if len(series) > 0:
                sources[col] = {
                    "available": len(series),
                    "total": len(cmp),
                    "coverage_pct": round(len(series) / len(cmp) * 100, 1),
                    "first": str(series.index.min()),
                    "last": str(series.index.max()),
                }

    # Condition comparison: Yandex rain-conditions vs actual rain
    if "yx_condition" in cmp.columns and "rain_truth" in grid.columns and "om_precip" in grid.columns:
        truth_hourly = (
            grid[["rain_truth", "om_precip"]]
            .resample("1h")
            .max()
        )
        yx_rain_conds = cmp["yx_condition"].apply(
            lambda c: 1 if isinstance(c, str) and c in ("rain", "rainy", "shower", "drizzle", "thunderstorm") else 0
        )
        
        yx_rain_hours = set(str(t) for t in yx_rain_conds[yx_rain_conds == 1].index)
        actual_rain_hours = set(str(t) for t in truth_hourly[truth_hourly["rain_truth"] == 1].index)
        
        intersect = yx_rain_hours & actual_rain_hours
        
        yandex_vs_truth = {
            "yandex_rain_hours": len(yx_rain_hours),
            "actual_rain_hours": len(actual_rain_hours),
            "agreement_hours": len(intersect),
            "yandex_only": len(yx_rain_hours - actual_rain_hours),
            "actual_only": len(actual_rain_hours - yx_rain_hours),
        }
    else:
        yandex_vs_truth = None

    return {
        "data_coverage": sources,
        "yandex_vs_truth": yandex_vs_truth,
    }


def generate_summary(report: dict) -> str:
    """Generate a human-readable text summary from the JSON report."""
    meta = report["metadata"]
    scores = report["scoring"]["scores"]
    best = report["scoring"]["best_overall"]
    tuning = report["param_tuning"]
    cc = report["cross_check"]

    lines = []
    lines.append("=" * 70)
    lines.append("RAIN PREDICTION ANALYSIS REPORT")
    lines.append("=" * 70)
    lines.append(f"Generated: {meta['generated_at']}")
    lines.append(f"Data range: {meta['data_stats']['grid_start']} → {meta['data_stats']['grid_end']}")
    lines.append(f"Rain threshold: {meta['config']['rain_threshold_mm']} mm/h")
    lines.append(f"Decision threshold: {meta['config']['decision_threshold']}%")
    lines.append("")

    # Data coverage
    lines.append("--- DATA COVERAGE ---")
    for col, info in cc.get("data_coverage", {}).items():
        lines.append(f"  {col}: {info['available']}/{info['total']} points ({info['coverage_pct']}%)")
    lines.append("")

    # Yandex comparison
    if cc.get("yandex_vs_truth"):
        yv = cc["yandex_vs_truth"]
        lines.append("--- YANDEX vs TRUTH ---")
        lines.append(f"  Yandex flagged rain: {yv['yandex_rain_hours']} hours")
        lines.append(f"  Actual rain: {yv['actual_rain_hours']} hours")
        lines.append(f"  Both agree: {yv['agreement_hours']} hours")
        lines.append(f"  Yandex false alarms: {yv['yandex_only']} hours")
        lines.append(f"  Yandex misses: {yv['actual_only']} hours")
        lines.append("")

    # Model scores
    lines.append("--- MODEL PERFORMANCE (at {}% threshold) ---".format(meta["config"]["decision_threshold"]))
    header = f"  {'Model':<22} {'Prec':>6} {'Recall':>6} {'F1':>6} {'TP':>5} {'FP':>5} {'FN':>5}"
    lines.append(header)
    lines.append("  " + "-" * len(header) + "--------")
    for name, s in scores.items():
        if s["precision"] is not None:
            lines.append(
                f"  {name:<22} {s['precision']:>6.3f} {s['recall']:>6.3f} {s['f1']:>6.3f} "
                f"{s['tp']:>5} {s['fp']:>5} {s['fn']:>5}"
            )
        else:
            lines.append(f"  {name:<22}   N/A   N/A   N/A   {s['tp']:>5} {s['fp']:>5} {s['fn']:>5}")
    lines.append("")

    # Best overall
    if best:
        lines.append("--- BEST OVERALL (F-beta=2, rain-warning trade-off) ---")
        lines.append(f"  Model: {best['model']}")
        lines.append(f"  Threshold: {best['threshold']}%")
        lines.append(f"  F-beta: {best['fbeta']:.3f}")
        lines.append("")

    # Parameter tuning
    lines.append("--- PARAMETER TUNING ---")
    lines.append(f"  Combinations tried: {tuning['total_combinations']}")
    if tuning.get("best_params"):
        bp = tuning["best_params"]
        lines.append(f"  Best (by F1): {bp.get('f1', 'N/A')}")
        lines.append(f"    proximity_divisor={bp.get('proximity_divisor')}, "
                     f"hysteresis_decay={bp.get('hysteresis_decay')}, "
                     f"trend_gain={bp.get('trend_gain')}")
        lines.append(f"    precision={bp.get('precision')}, recall={bp.get('recall')}")
    lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Plotting (optional — requires matplotlib)
# ---------------------------------------------------------------------------

def save_plots(grid: pd.DataFrame, config: AnalysisConfig, output_dir: str) -> list[str]:
    """§8: Save PNG plots. Returns list of file paths."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        print("[WARN] matplotlib not available — skipping plots", file=sys.stderr)
        return []

    saved = []
    os.makedirs(output_dir, exist_ok=True)

    # Plot 1: Timeline overlay
    fig, axes = plt.subplots(3, 1, figsize=(16, 10), sharex=True)
    hourly = grid.resample("1h").last()

    # Panel A: Temperature + Humidity
    ax = axes[0]
    if "temp" in hourly.columns:
        ax.plot(hourly.index, hourly["temp"], color="tab:red", alpha=0.7, label="local temp (°C)")
    if "om_temp" in hourly.columns:
        ax.plot(hourly.index, hourly["om_temp"], color="tab:red", ls="--", alpha=0.4, label="OM temp")
    if "yx_temp" in hourly.columns:
        ax.plot(hourly.index, hourly["yx_temp"], color="tab:red", ls=":", alpha=0.4, label="Yandex temp")
    ax.set_ylabel("Temp (°C)")
    ax.legend(loc="upper left", fontsize=7)
    ax.grid(True, alpha=0.3)

    # Panel B: Spread + derivative
    ax = axes[1]
    if "spread" in hourly.columns:
        ax.plot(hourly.index, hourly["spread"], color="tab:cyan", label="spread (°C)")
    ax2 = ax.twinx()
    if "spread_deriv" in hourly.columns:
        ax2.plot(hourly.index, hourly["spread_deriv"], color="tab:purple", alpha=0.5, label="spread derivative (°C/h)")
    ax.set_ylabel("Spread (°C)")
    ax2.set_ylabel("Deriv (°C/h)", color="tab:purple")
    ax2.tick_params(axis="y", labelcolor="tab:purple")
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=7)
    ax.grid(True, alpha=0.3)

    # Panel C: Rain predictions + truth
    ax = axes[2]
    if "rain_truth" in grid.columns and "om_precip" in grid.columns:
        truth_h = grid[["rain_truth", "om_precip"]].resample("1h").max()
        mask = truth_h["rain_truth"] == 1
        if mask.any():
            ax.fill_between(truth_h.index, 0, truth_h["om_precip"],
                            where=mask, color="tab:blue", alpha=0.15, label="actual rain (mm)")
    model_cols = [c for c in grid.columns if c.startswith("model_")]
    colors = ["tab:orange", "tab:green", "tab:red"]
    for i, col in enumerate(model_cols):
        mh = grid[col].resample("1h").mean()
        ax.plot(mh.index, mh, color=colors[i % len(colors)], alpha=0.8, label=col)
    ax.axhline(config.decision_threshold, color="gray", ls="--", alpha=0.5, lw=1,
               label=f"threshold {config.decision_threshold}%")
    ax.set_ylabel("Rain prob (%)")
    ax.set_xlabel("Time (UTC)")
    ax.legend(loc="upper left", fontsize=7)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    path = os.path.join(output_dir, "timeline.png")
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    saved.append(path)

    # Plot 2: Threshold calibration (best model = tuned)
    if "model_tuned" in grid.columns:
        fig, ax = plt.subplots(figsize=(10, 5))
        rl.plot_calibration(
            grid["model_tuned"], grid["rain_truth"],
            betas=config.betas,
            title="Tuned model — threshold calibration"
        )
        path = os.path.join(output_dir, "calibration_tuned.png")
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        saved.append(path)

    return saved


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_report(grid: pd.DataFrame, stats: dict, config: AnalysisConfig,
                 output_dir: str, plot_paths: list[str]) -> dict:
    """Assemble the full JSON report."""
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "script_version": "1.0.0",
            "config": {
                "rain_threshold_mm": config.rain_threshold_mm,
                "decision_threshold": config.decision_threshold,
                "deriv_window": config.deriv_window,
                "grid_freq": config.grid_freq,
                "model_params": config.model_params,
            },
            "data_stats": stats,
        },
        "scoring": score_models(grid, config),
        "param_tuning": param_tuning(grid, config),
        "cross_check": cross_check(grid),
        "plots": plot_paths,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Rain prediction analysis — automated CLI runner"
    )
    parser.add_argument("--ha-csv", required=True, help="Path to HA history CSV export")
    parser.add_argument("--om-sources", nargs="+", default=[],
                        help="Open-meteo JSON file(s)")
    parser.add_argument("--yandex-dir", default=None,
                        help="Yandex archive directory (recursive JSON glob)")
    parser.add_argument("--output", "-o", default="analysis_report.json",
                        help="Output JSON report path")
    parser.add_argument("--plots", action="store_true",
                        help="Generate PNG plots alongside report")
    parser.add_argument("--threshold", type=float, default=50.0,
                        help="Decision threshold %% for classification (default: 50)")
    parser.add_argument("--rain-threshold", type=float, default=0.1,
                        help="Min precip mm/h to label as rain (default: 0.1)")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Suppress text summary on stdout")

    args = parser.parse_args()

    config = AnalysisConfig(
        ha_csv=args.ha_csv,
        om_sources=args.om_sources,
        yandex_dir=args.yandex_dir,
        decision_threshold=args.threshold,
        rain_threshold_mm=args.rain_threshold,
    )

    output_dir = os.path.dirname(os.path.abspath(args.output)) or "."

    # Pipeline
    grid, stats = load_data(config)
    grid = compute_features(grid, config)
    grid, gt_stats = label_ground_truth(grid, config)
    grid, model_stats = run_models(grid, config)

    stats["ground_truth"] = gt_stats
    stats["model_summary"] = model_stats

    # Plots (optional)
    plot_paths = save_plots(grid, config, output_dir) if args.plots else []

    # Build report
    report = build_report(grid, stats, config, output_dir, plot_paths)

    # Save JSON
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2, default=str, ensure_ascii=False)

    if not args.quiet:
        print(generate_summary(report))
        print(f"\nJSON report: {args.output}")
        if plot_paths:
            print(f"Plots: {', '.join(plot_paths)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
