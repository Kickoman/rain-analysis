# Reports Directory

This directory contains auto-generated analysis results — daily summaries,
model performance reports, pressure variant comparisons, and timestamped
full-run outputs (JSON, PNG plots, Markdown).

## Why These Are Tracked in Git

Reports **are intentionally committed** to the repository for:

- **Historical reference** — compare model performance over time
- **Reproducibility** — each analysis run is linked to the exact model version
- **CI/CD artifacts** — automated runs publish these to GitHub Pages

## Directory Structure

```
reports/
├── daily/          # Daily-performance summaries (Markdown)
├── YYYYMMDD_HHMMSS/  # Timestamped full analysis runs
├── 2026-07-13.md   # Quick daily summaries (flat files)
└── pressure_variants_*.md  # Pressure model comparisons
```

## When Running Analysis

Results land here automatically via:

```bash
# Single analysis run (outputs to specified file)
python run_analysis.py \
    --ha-csv data/ha.csv \
    --om-sources data/openmeteo.json \
    --output reports/analysis_2026-07-20.json \
    --plots

# Full pipeline (outputs to directory)
python run_full_analysis.py --days 7 --output-dir reports/
```

## Keeping It Clean

- Add new results on top of old ones — don't delete history
- If a daily report is noise (e.g., no data window), overwrite rather than
  accumulating stale copies
- Large generated files (multi-MB JSON, heavy PNGs) should eventually be
  moved to `.gitignore` — for now the outputs are small enough to track
