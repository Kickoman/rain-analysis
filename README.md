# Rain Prediction Backtesting Lab

Offline toolkit to replay and tune your Home Assistant rain-probability model against
real precipitation data.

## Quick Start

### Interactive Analysis (Notebook)

```bash
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
# 1. Fetch Home Assistant sensor history
python fetch_ha_data.py --days 7 --output data/ha.csv

# 2. Run analysis
python run_analysis.py \
    --ha-csv data/ha.csv \
    --om-sources data/openmeteo.json \
    --yandex-dir data/yandex_archive/ \
    --output-dir reports/ \
    --plots
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
│   ├── MODELS.md             # All models documentation
│   ├── CLI_RUNNER.md         # CLI script documentation
│   ├── DATA_SOURCES.md       # Data collection guide
│   └── HA_DATA_FETCHER.md    # HA fetcher details
├── CONTRIBUTING.md           # Development guide
├── reports/                  # Generated analysis results (intentionally tracked)
├── data/                     # Your local data files (gitignored)
└── requirements.txt
```

## The Mental Model

```
  local sensors ─┐
  open-meteo   ──┼──►  one 10-min UTC grid  ──►  derive spread/derivative
  yandex        ─┘                                       │
                                                         ▼
                          candidate models (tunable ModelParams)
                                                         │
                                                         ▼
                        score vs open-meteo precip (precision/recall/F1/lead-time)
```

- Every HA helper (dew point, spread, derivative, rain_probability) has a pure-Python twin in `rainlib.py`
- Ground truth = open-meteo hourly precipitation. `rain_truth=1` when precip ≥ threshold
- Models are in the `MODELS` registry: `original`, `tuned`, `trend_dominant`, `ha_live`, `pressure_aware`, `pressure_absolute`, `pressure_long_window`, `pressure_lagged`, `pressure_combined`

## Data Sources

### 1. Home Assistant (Local Sensors)

Required entities:
- `sensor.datchik_klimata_temperatura` — outdoor temperature
- `sensor.datchik_klimata_vlazhnost` — outdoor humidity
- `sensor.filtered_pressure` — atmospheric pressure (for pressure-aware models)
- `sensor.rain_probability` — live model output

Fetch with:
```bash
python fetch_ha_data.py --days 7 --output data/ha.csv
```

### 2. Open-Meteo (Ground Truth)

Historical precipitation data for validation.
- API: https://open-meteo.com/
- Location: Minsk (53.930716, 27.596646)
- See documentation for fetching details

### 3. Yandex Weather (Comparison)

Archive of Yandex weather snapshots for cross-checking.
- Archive available at: http://10.8.0.4:7005/weather.tgz
- Updated hourly

## Adding Data Over Time

Just append new data — everything scales without code changes:
- Drop new open-meteo JSON files into `OM_SOURCES`
- Add new Yandex snapshots to the archive folder
- Fetch a longer HA CSV export

## Core Concepts

### ModelParams

All tuning knobs in one place:

| Param | Meaning |
|-------|---------|
| `proximity_divisor` | Spread (°C) that maps to 0% proximity |
| `trend_gain` | Points added per °C/h of spread narrowing |
| `trend_floor` / `trend_ceiling` | Clamp on trend contribution |
| `proximity_weight` / `trend_weight` | Blend weights |
| `dry_spread_cutoff` / `dry_ceiling` | Cap output when air is dry |
| `hysteresis_decay` | Decay speed after peak (0=frozen, 1=instant) |
| `derivative_window` | Window for spread derivative (1h=twitchy, 3h=smooth) |
| `pressure_weight` | Weight of pressure term in blend |
| `pressure_gain` | Points per hPa/h of pressure drop |
| `pressure_floor` / `pressure_ceiling` | Clamp on pressure contribution |
| `pressure_window` | Time window for pressure derivative |
| `pressure_drop_threshold` | Min hPa/h to activate pressure signal |

### Adding a New Model

1. Define the model in `rainlib.py`:
   ```python
   def model_my_custom(ctx: ModelContext, p: ModelParams | None = None) -> pd.Series:
       # your logic
       return score_series
   ```

2. Register it in `MODELS`:
   ```python
   MODELS = {
       "original": model_original,
       "tuned": model_tuned,
       "my_custom": model_my_custom,  # ← add here
   }
   ```

3. Re-run — it appears everywhere automatically

### Pressure Integration (✅ Implemented)

Barometric pressure is now integrated into the analysis framework. Five
pressure-aware models are available:

| Model | Description |
|-------|-------------|
| `pressure_aware` | Baseline pressure-trend model (proximity + trend + pressure derivative) |
| `pressure_absolute` | Adds absolute pressure level bonus (<1000 hPa = rain indicator) |
| `pressure_long_window` | Uses 12h pressure derivative window for slow weather systems |
| `pressure_lagged` | Uses pressure lagged by 6h to account for storm travel time |
| `pressure_combined` | Combines all techniques (long window + lagged + absolute) |

**Required sensor:** `sensor.filtered_pressure` (hPa) — from Home Assistant's
filter integration smoothing raw pressure readings.

**Pressure data sources** (via `build_pressure_series()`):

| Priority | Source | Column | Unit |
|----------|--------|--------|------|
| 1 | HA `filtered_pressure` | `pressure` | hPa |
| 2 | Meteostat | `ms_pres` | hPa |
| 3 | Yandex Archive | `yx_pressure_mm` | mm Hg → hPa |

When no pressure data is available, models gracefully fall back to
spread+trend only (same as `tuned`).

For details, see [MODELS.md#pressure-aware-models](docs/MODELS.md) and
`pressure_variants.py`.

## Known Findings

- **Post-peak crash:** Raw humidity dips mid-rain; hysteresis prevents false recovery
- **Dry-night false positive:** Calm nights close the spread like rain nights → surface humidity alone can't separate them
- **Pressure is key:** Not a tuning issue — fundamental limitation without barometric data

## Documentation

- [Models Documentation](docs/MODELS.md) — complete guide to all rain prediction models
- [Baseline Model Analysis](docs/BASELINE_MODEL.md) — detailed breakdown of v0.1
- [Data Sources Guide](docs/DATA_SOURCES.md) — how to fetch all 4 data sources
- [CLI Runner Guide](docs/CLI_RUNNER.md) — automated analysis script
- [HA Data Fetcher](docs/HA_DATA_FETCHER.md) — sensor history export

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow and best practices.

## License

Private repository — Kickoman/rain-analysis
