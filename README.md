# Rain Prediction Backtesting Lab

Offline toolkit to replay and tune your Home Assistant rain-probability model against
real precipitation data.

## Quick Start

### Interactive Analysis (Notebook)

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install pandas numpy matplotlib jupyter
jupyter notebook rain_analysis.ipynb
```

**Standalone mode:** The notebook can fetch data automatically. Edit the configuration cell at the top:

```python
# CONFIGURATION
HA_CSV = 'data/ha.csv'
OM_SOURCES = ['data/openmeteo.json']
YANDEX_DIR = 'data/yandex/'
METEOSTAT_JSON = 'data/meteostat.json'
```

Then uncomment the optional data fetching cells to run the fetch scripts directly from the notebook.

### Automated Analysis (CLI)

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install pandas numpy matplotlib

# 1. Fetch Home Assistant sensor history
python fetch_ha_data.py --days 7 --output data/ha.csv

# 2. Run analysis (single report)
python run_analysis.py \
    --ha-csv data/ha.csv \
    --om-sources data/openmeteo.json \
    --yandex-dir data/yandex_archive/ \
    --output reports/analysis_2026-07-20.json \
    --plots

# Or run the full pipeline (fetch + analyze)
python run_full_analysis.py --days 7 --output-dir reports/
```

See [docs/CLI_RUNNER.md](docs/CLI_RUNNER.md) for full CLI documentation.

## Repository Structure

```
rain-analysis/
├── rain_analysis.ipynb      # Interactive Jupyter notebook
├── rainlib.py                # Core analysis engine (physics, models, metrics)
├── run_analysis.py           # Automated CLI analysis script
├── run_full_analysis.py      # Complete pipeline (fetch + analyze)
├── fetch_ha_data.py          # Home Assistant data fetcher
├── fetch_openmeteo.py        # Open-Meteo API client
├── fetch_meteostat.py        # Meteostat API client
├── fetch_yandex_archive.py   # Yandex Weather archive downloader
├── docs/
│   ├── BASELINE_MODEL.md     # Current model analysis (v0.1)
│   ├── CLI_RUNNER.md         # Full CLI documentation
│   ├── DATA_SOURCES.md       # Ground-truth & model comparison
│   ├── GLOSSARY.md           # ML metrics definitions (Precision, Recall, F1, F2)
│   ├── MODELS.md             # Model variants & results
│   ├── THRESHOLD_SWEEP.md    # Threshold optimization guide
│   └── CONTRIBUTING.md       # Development workflow
├── data/                     # Input data (git-ignored except .gitkeep)
├── reports/                  # Analysis outputs (JSON + plots)
└── tests/                    # Automated test suite
```

## Features

- **Multiple ground-truth sources:** Home Assistant, Open-Meteo, Meteostat, Yandex Weather
- **Physics-based models:** Baseline, pressure-aware, hysteresis variants
- **Threshold optimization:** Automated sweep with multi-metric scoring
- **Rich metrics:** Brier score, calibration, reliability, F1, precision/recall
- **Reproducible:** CLI-first design, JSON outputs, automated plots
- **Well-tested:** 100+ tests covering models, fetchers, metrics, edge cases

## Data Sources

### Ground Truth (Precipitation)

| Source | Type | Coverage | Quality |
|--------|------|----------|---------|
| **Home Assistant** | Local sensor | Your location, continuous | ⭐⭐⭐ Reference |
| **Open-Meteo** | Reanalysis | Global, 1h resolution | ⭐⭐⭐ Good |
| **Meteostat** | Station archive | Station-based | ⭐⭐ Variable |
| **Yandex Weather** | Archive scrape | Limited locations | ⭐ Unreliable |

### Model Predictions

| Source | What It Is | Data Window |
|--------|------------|-------------|
| **HA rain_probability** | Your production model | Any timeframe |
| **Built-in models** | Reference implementations | Experimental |

See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) for fetcher usage and data quality details.

## Documentation

- **[GLOSSARY.md](docs/GLOSSARY.md)** — Definitions of ML metrics (Precision, Recall, F1, F2, Confusion Matrix)
- **[MODELS.md](docs/MODELS.md)** — All rain prediction models and their performance
- **[BASELINE_MODEL.md](docs/BASELINE_MODEL.md)** — Current production model analysis
- **[CLI_RUNNER.md](docs/CLI_RUNNER.md)** — Complete CLI usage guide
- **[DATA_SOURCES.md](docs/DATA_SOURCES.md)** — Ground truth data sources and quality
- **[THRESHOLD_SWEEP.md](docs/THRESHOLD_SWEEP.md)** — Threshold optimization methodology
- **[CONTRIBUTING.md](docs/CONTRIBUTING.md)** — Development workflow

## Models

The toolkit includes reference implementations of various rain prediction approaches:

- **Baseline** — dew-point depression only (current HA model v0.1)
- **Pressure-aware** — adds atmospheric pressure trend
- **Hysteresis** — stateful model with memory
- **Pressure variants** — experimental A/B/C/D approaches

Each model outputs a continuous probability (0–100%) that can be tuned via threshold sweeps.

See [docs/MODELS.md](docs/MODELS.md) for detailed model descriptions and performance comparisons.

## Metrics

The analysis computes:

- **Brier Score** — probabilistic accuracy (lower is better, 0 = perfect)
- **Calibration Slope** — reliability (1.0 = ideal, <1 = underconfident, >1 = overconfident)
- **F1 Score** — binary classification balance
- **Precision / Recall** — at configurable decision threshold
- **Confusion Matrix** — TP/FP/TN/FN breakdown

## Threshold Optimization

Automated sweep finds the best decision threshold for your model:

```bash
python run_analysis.py \
    --ha-csv data/ha.csv \
    --om-sources data/openmeteo.json \
    --threshold-sweep \
    --output reports/sweep_2026-07-20.json
```

Uses weighted scoring: `F1 + Brier_inverse + Calibration_quality`

See [docs/THRESHOLD_SWEEP.md](docs/THRESHOLD_SWEEP.md) for methodology and interpretation.

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=term-missing

# Run specific test file
pytest tests/test_rainlib.py -v
```

## Contributing

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for:
- Code style guidelines
- Testing requirements
- PR workflow

## Requirements

- Python 3.8+
- pandas, numpy, matplotlib
- pytest (for development)

No Home Assistant integration required — this is a standalone offline toolkit.

## License

MIT
