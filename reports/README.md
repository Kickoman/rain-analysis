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
├── YYYY-MM-DD.md            # The daily report — one per day, flat
├── daily/YYYY-MM-DD/full/   # That day's run: analysis_report.json (tracked)
│                            # and grid.csv (gitignored, regenerable)
├── daily/YYYY-MM-DD/{7,14,28}d/  # Archived runs of the retired 3-window flow
└── pressure_variants_*.md   # Pressure model comparisons
```

**Two report formats live here.** Files from 2026-07-18 onward are the
onset-first format: one verdict, one scoreboard on rain starts, the last day,
data health — about 65 lines. Files 2026-07-13..17 are the earlier
eleven-section nowcast format (~390 lines), kept as published history.
Everything the shorter report leaves out is still computed into the
`analysis_report.json` beside it.

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
