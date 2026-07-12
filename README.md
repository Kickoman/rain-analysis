# Rain Prediction Backtesting Lab

Offline toolkit to replay and tune your Home Assistant rain-probability model against
real precipitation data.

## Files

| File | What it is |
|------|-----------|
| `rain_analysis.ipynb` | The notebook — start here. Loads data, runs models, scores & plots. |
| `rainlib.py` | The engine. All physics, HA-helper reimplementations, models, metrics. Import it; edit it to add features/models. |
| `build_notebook.py` | Regenerates the `.ipynb` (only needed if you want to rebuild it). |
| `ha_full.csv` | Your HA history export (sample included). |
| `om_example.json` | An open-meteo response (sample included). |
| `yandex_archive/` | Folder of your Yandex `fact` JSON snapshots (sample included). |

## Setup

```bash
pip install pandas numpy matplotlib jupyter
jupyter notebook rain_analysis.ipynb
```

Then run cells top to bottom. Edit the paths in **§1** to point at your own exports.

## The mental model

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

- Every HA helper you built (dew point, spread, absolute humidity, humidex, derivative,
  rain_probability) has a pure-Python twin in `rainlib.py`, so what you tune here maps
  straight back to HA templates.
- Ground truth = open-meteo hourly precipitation. `rain_truth=1` when precip ≥ threshold.
- Models are in the `MODELS` registry: `original`, `tuned`, `trend_dominant`. Add your own.

## Adding data over time

Just append. Drop new open-meteo JSON files into `OM_SOURCES`, new Yandex snapshots into
the archive folder, and a longer HA CSV export. Everything scales — no code changes.

## Adding a pressure-aware model (recommended next step)

Once you have a BME280 logging pressure into HA:

1. Export pressure in the same CSV and add it to `HA_ENTITIES` (e.g. `'sensor.pressure':'pressure'`).
2. In `rainlib.py`, compute `grid['pressure_deriv'] = derivative(grid['pressure'], '3h')`.
3. Write `model_pressure_aware(...)` that fires on a pressure **drop rate**, and register it in `MODELS`.
4. Re-run — the scoring and plots pick it up automatically.

## Tuning knobs (`ModelParams`)

| Param | Meaning |
|-------|---------|
| `proximity_divisor` | Spread (°C) that maps to 0% proximity. Lower = reaches high prob sooner. |
| `trend_gain` | Points added per °C/h of spread narrowing. |
| `trend_floor` / `trend_ceiling` | Clamp on how much the trend term can subtract / add. |
| `proximity_weight` / `trend_weight` | Blend weights. |
| `dry_spread_cutoff` / `dry_ceiling` | If spread above cutoff, cap output (suppress dry-air noise). |
| `hysteresis_decay` | 0 = frozen once high, 1 = no hysteresis. Controls decay speed after a peak. |
| `derivative_window` | Trailing window for the spread derivative (`1h` twitchy, `3h` smooth). |

## Known findings baked into the design

- **Post-peak crash:** raw humidity dips mid-rain; hysteresis stops the score collapsing while it's still raining.
- **Dry-night false positive:** ordinary calm nights close the spread as tightly as real rain nights → surface humidity alone can't separate them. This is *why* pressure is the key missing feature, not just a tuning issue.
