# Rain Prediction Backtesting Lab

Offline toolkit to replay and tune your Home Assistant rain-probability model against
real precipitation data.

## Quick Start

### Interactive Analysis (Notebook)

```bash
pip install pandas numpy matplotlib jupyter
jupyter notebook rain_analysis.ipynb
```

### Automated Analysis (CLI)

```bash
# 1. Fetch Home Assistant sensor history
python fetch_ha_data.py --days 7 --output data/ha.csv

# 2. Run analysis
python run_analysis.py \
    --ha-csv data/ha.csv \
    --om-sources data/openmeteo.json \
    --yandex-dir data/yandex_archive/ \
    --output report.json \
    --plots
```

See [docs/CLI_RUNNER.md](docs/CLI_RUNNER.md) for full CLI documentation.

## Repository Structure

```
rain-analysis/
├── rain_analysis.ipynb      # Interactive Jupyter notebook
├── rainlib.py                # Core analysis engine (physics, models, metrics)
├── run_analysis.py           # Automated CLI analysis script
├── fetch_ha_data.py          # Home Assistant data fetcher
├── docs/
│   ├── BASELINE_MODEL.md     # Current model analysis (v0.1)
│   ├── CLI_RUNNER.md         # CLI script documentation
│   └── HA_DATA_FETCHER.md    # Data fetching guide
├── data/                     # Your local data files (gitignored)
└── requirements.txt
```

## The Mental Model

```
  local sensors ─┐
  open-meteo   ──┼──►  one 10-min UTC grid  ──►  derive spread/derivative
  yandex       ─┘                                        │
                                                         ▼
                          candidate models (tunable ModelParams)
                                                         │
                                                         ▼
                        score vs open-meteo precip (precision/recall/F1/lead-time)
```

- Every HA helper (dew point, spread, derivative, rain_probability) has a pure-Python twin in `rainlib.py`
- Ground truth = open-meteo hourly precipitation. `rain_truth=1` when precip ≥ threshold
- Models are in the `MODELS` registry: `original`, `tuned`, `trend_dominant`

## Data Sources

### 1. Home Assistant (Local Sensors)

Required entities:
- `sensor.datchik_klimata_temperatura` — outdoor temperature
- `sensor.datchik_klimata_vlazhnost` — outdoor humidity
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

### Adding a New Model

1. Define the model in `rainlib.py`:
   ```python
   def model_my_custom(spread, spread_deriv, p=None):
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

### Pressure Integration (Recommended Next Step)

The baseline model hits a ceiling without pressure. To add it:

1. Export pressure from HA: `sensor.office_weather_station_pressure`
2. Add to `HA_ENTITIES`: `'sensor.pressure': 'pressure'`
3. Compute derivative: `grid['pressure_deriv'] = derivative(grid['pressure'], '3h')`
4. Write `model_pressure_aware()` that fires on pressure **drop rate**
5. Register in `MODELS` — scoring/plots work unchanged

## Known Findings

- **Post-peak crash:** Raw humidity dips mid-rain; hysteresis prevents false recovery
- **Dry-night false positive:** Calm nights close the spread like rain nights → surface humidity alone can't separate them
- **Pressure is key:** Not a tuning issue — fundamental limitation without barometric data

## Documentation

- [Baseline Model Analysis](docs/BASELINE_MODEL.md) — detailed breakdown of v0.1
- [CLI Runner Guide](docs/CLI_RUNNER.md) — automated analysis script
- [HA Data Fetcher](docs/HA_DATA_FETCHER.md) — sensor history export

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow and best practices.

## License

Private repository — Kickoman/rain-analysis
