# CLI Analysis Runner

Automated script for running the rain-prediction analysis pipeline without Jupyter.

## Overview

`run_analysis.py` replicates the full analysis flow from `rain_analysis.ipynb`:
data loading → feature computation → model scoring → threshold sweeps →
parameter tuning → cross-check — all using the same `rainlib.py` functions.

The output is a **JSON report** designed to be readable by both humans and LLMs.

## Quick Start

```bash
pip install pandas numpy matplotlib   # same deps as the notebook

python run_analysis.py \
    --ha-csv data/ha_full.csv \
    --om-sources data/om.json \
    --yandex-dir data/2026/ \
| `--meteostat` | | `None` | Meteostat JSON file |
    --output analysis_report.json \
    --plots
```

## Arguments

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--ha-csv` | ✓ | — | Path to Home Assistant history CSV export |
| `--om-sources` | | `[]` | One or more open-meteo JSON files |
| `--yandex-dir` | | `None` | Directory with Yandex `fact` JSON snapshots |
| `--meteostat` | | `None` | Meteostat JSON file |
| `--output`, `-o` | | `analysis_report.json` | Where to write the JSON report |
| `--plots` | | off | Also generate PNG timeline + calibration plots |
| `--threshold` | | `50.0` | Probability threshold for rain/no-rain decision |
| `--rain-threshold` | | `0.1` | Minimum precipitation (mm/h) to label as rain |
| `--quiet`, `-q` | | off | Suppress text summary on stdout |

> **Tip:** Pass multiple open-meteo files with `--om-sources data/day1.json data/day2.json`.

## Output Files

### `analysis_report.json`

The main output. Structure:

```json
{
  "metadata": {
    "generated_at": "2026-07-12T19:30:00+00:00",
    "script_version": "1.0.0",
    "config": { ... },
    "data_stats": {
      "ha_rows": 1111,
      "grid_shape": [860, 17],
      "grid_start": "...",
      "grid_end": "...",
      "ground_truth": {
        "total_rain_hours": 47,
        "rain_hours": [{"time": "...", "precip_mm": 1.9}, ...]
      },
      "model_summary": {
        "original": {"mean": 24.1, "std": 20.3, ...},
        ...
      }
    }
  },
  "scoring": {
    "scores": {
      "original": {"precision": 0.68, "recall": 0.23, "f1": 0.35, ...},
      "tuned": { ... },
      "trend_dominant": { ... },
      "ha_live": { ... }
    },
    "threshold_sweeps": { ... },
    "fbeta_recommendations": {
      "tuned": {
        "beta_0.5": {"best_threshold": 80, "precision": 0.76, ...},
        "beta_1.0": {"best_threshold": 55, ...},
        "beta_2.0": {"best_threshold": 5, ...}
      }
    },
    "best_overall": {"model": "tuned", "threshold": 55, "fbeta": 0.42}
  },
  "param_tuning": {
    "total_combinations": 36,
    "best_params": {"proximity_divisor": 7, "hysteresis_decay": 0.2, ...},
    "top_15": [ ... ]
  },
  "cross_check": {
    "data_coverage": { ... },
    "yandex_vs_truth": {
      "yandex_rain_hours": 12,
      "actual_rain_hours": 47,
      "agreement_hours": 8
    }
  },
  "plots": ["timeline.png", "calibration_tuned.png"]
}
```

### Plots (when `--plots` is used)

| File | What |
|------|------|
| `timeline.png` | 3-panel timeline: temperature, spread+deriv, rain predictions vs truth |
| `calibration_tuned.png` | Precision/recall/F-beta vs threshold for the tuned model |

## Text Summary

Every run prints a human-readable summary to stdout (suppress with `--quiet`):

```
======================================================================
RAIN PREDICTION ANALYSIS REPORT
======================================================================
Generated: 2026-07-12T19:30:00+00:00
Data range: 2026-06-30 21:00 → 2026-07-06 20:10

--- MODEL PERFORMANCE (at 50% threshold) ---
  Model                  Prec Recall     F1    TP    FP    FN
  -------------------------------------------------------------
  original              0.683  0.233  0.348    60    28   198
  tuned                 0.674  0.227  0.340    62    30   208
  trend_dominant        0.614  0.100  0.170    27    17   243
  ha_live               0.565  0.153  0.241    39    30   216

--- PARAMETER TUNING ---
  Combinations tried: 36
  Best (by F1): 0.385
    proximity_divisor=7, hysteresis_decay=0.2, trend_gain=20
    precision=0.67, recall=0.27
```

## Relationship to the Notebook

| Notebook section | Script |
|------------------|--------|
| §1 — Point at data | `--ha-csv`, `--om-sources`, `--yandex-dir` flags |
| `--meteostat` | | `None` | Meteostat JSON file |
| §2 — Load & align | `load_data()` → `rl.build_grid()` |
| §3 — Features | `compute_features()` → same rainlib functions |
| §4 — Ground truth | `label_ground_truth()` → `rl.label_rain()` |
| §5 — Run models | `run_models()` → `MODELS[name]()` |
| §6 — Score | `score_models()` → `rl.confusion_at_threshold()`, `rl.lead_time()` |
| §7 — Threshold sweep | `score_models()` → `rl.sweep_threshold()`, `rl.recommend_threshold()` |
| §8 — Timeline plot | `save_plots()` (optional) |
| §9 — Cross-check | `cross_check()` |
| §10 — Parameter tuning | `param_tuning()` |

**No divergence.** The script imports and calls `rainlib.py` functions directly.
When you add a new model or feature to `rainlib.py`, the script picks it up
without changes (as long as it's in the `MODELS` registry).

## LLM-Friendly Design

The JSON report is intentionally structured for AI consumption:

- **No images needed** — all metrics are in numeric/text form
- **Flat dicts** — no deeply nested structures, easy to parse
- **Complete state** — metadata, config, and all scores in one file
- **Consistent naming** — same model/param names as in `rainlib.py`

An LLM reading the report can:
1. Check data coverage and quality
2. Compare model performance at a glance
3. Identify the best threshold for a given trade-off
4. See parameter tuning results
5. Understand how Yandex predictions compare to reality

## Adding New Models

1. Define the model function in `rainlib.py` with the `ModelContext` signature:
   ```python
   def model_my_custom(ctx: ModelContext,
                       p: ModelParams | None = None) -> pd.Series:
       """My custom rain prediction model."""
       # Extract what you need from context
       spread = ctx.spread
       spread_deriv = ctx.spread_deriv
       # ... your logic here ...
       return score_series
   ```

2. Register it in the `MODELS` dictionary:
   ```python
   MODELS = {
       "original": model_original,
       "tuned": model_tuned,
       "trend_dominant": model_trend_dominant,
       "my_custom": model_my_custom,   # ← add this line
   }
   ```

3. That's it. Re-run `run_analysis.py` — the new model appears in scores,
   threshold sweeps, and all outputs automatically.

## Scheduled Runs

This script is designed to be run by an AI assistant (or cron job):

```bash
# Daily run
python run_analysis.py \
    --ha-csv data/ha_full.csv \
    --om-sources data/om.json \
    --yandex-dir data/2026/ \
| `--meteostat` | | `None` | Meteostat JSON file |
    --output reports/$(date +%Y-%m-%d).json \
    --quiet
```

The script exits with code 0 on success, non-zero on error — suitable for
pipeline integration.
