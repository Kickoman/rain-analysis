# Changelog

Notable changes to rain-analysis.

## 2026-08-14

Implements `plans/model-improvements.md`. With the harness fixed the day before,
the models could finally be measured — and the measurement said the project was
built on its weakest signal. Over 49,200 hours the dew-point-spread derivative
that leads every model ranks at ROC AUC 0.49 (chance) while absolute pressure
reaches 0.75.

### Added

- **Threshold-free metrics.** `rainlib.roc_auc` and `rainlib.average_precision`,
  reported next to F1 everywhere. F1 at a fixed 50% cutoff had been hiding
  models that cannot rank at all: `ha_live` posted F1 0.313 at AUC 0.579,
  `trend_dominant` 0.234 at AUC 0.505. Implemented in-repo and checked against
  scikit-learn, including tie handling.
- **A warning target.** `rainlib.label_rain_within` labels "rain in any of the
  next N hours" (default 3), so ordinary precision and recall measure what an
  alert is for. The nowcast label is unchanged and still drives the published
  metric series; the warning target drives model selection.
- **Baselines** — persistence, always-alert and the Yandex forecast, in every
  report. There had never been a floor. There should have been: "always alert"
  scores F1 0.385 on the nowcast, beating eight of the ten hand-tuned models,
  and persistence scores 0.709, beating all of them.
- **`pressure_primary`** (`pressure_variants.py`) — weights set from measured
  single-feature AUC instead of by hand: pressure anomaly leads, humidity
  proximity is secondary, the spread derivative is a nudge, and the result is
  scaled by time of day (rain within 3h peaks at 11h UTC, 1.32× the base rate).
  Best physics model on the archive: nowcast AUC 0.637 against 0.633 for
  `combined` and 0.579 for the production replica.
- **`analysis/learned.py`** — causal feature builder, expanding-window
  walk-forward validation, and a calibrated logistic model with save/load that
  records its training window, features and coefficients. Scored on identical
  held-out rows it reaches AUC 0.753 on the 3-hour target against 0.669 for the
  best hand-tuned model and 0.494 for `ha_live`. Adds scikit-learn, imported
  lazily so the rest of the pipeline runs without it.
- **[ALERT_RULE.md](ALERT_RULE.md)** — a replacement for the deployed
  automation, with its measured scores and the old rule's beside it.

### Fixed

- **The absolute-pressure bonus was calibrated for sea level.** Cut-offs of
  990/1000/1005 hPa against a barometer at ~220 m, where station pressure has a
  median of 989.6 and never exceeds 1001: it returned 20 for 51.8% of hours, 10
  for 46.6%, and zero *never* — a constant +15 offset presented as a cyclone
  detector, which also shifted every score against the fixed decision threshold.
  Now a departure from the station's own 30-day median, which needs no elevation
  constant. Lifts the three models that use it by 0.009–0.013 AUC.
- **Grid search was scored on its own training window.** `param_tuning` now
  selects on the earlier 70% and reports on the rest. The gap is not subtle:
  selection F1 0.429, held-out F1 0.161.
- **`derivative()` returned all-NaN for a window at or below the sample
  spacing** — silently, because callers `.fillna(0.0)` the result into "no
  trend". On the hourly grid the ordinary-looking window `"1h"` did exactly
  this. It now raises.
- **`_setup_dataframe` forward-filled `spread` without a limit**, so a dead
  sensor propagated its last reading through the rest of the run, invisible to
  the coverage figures. Bounded to 3 hours.
- Open-Meteo fetches now include cloud cover and wind, and `_get_pressure_variant`
  no longer needs updating for each new model.

## 2026-08-13

Model scoring rested on ~17 labelled rain hours, which made every reported
ranking statistical noise. The cause was the measurement harness, not the
models. Benchmarks published before this date are superseded — see
[MODELS.md](MODELS.md).

### Added

- **`fetch_ha_statistics.py`** — reads Home Assistant long-term statistics over
  the WebSocket API. These survive recorder purging, which lifted the usable
  local history from ~10 days to 43 (1036 hourly points, 247 rain hours).
- **`archive_ha_data.py`** — append-only merge into `data/archive/ha_hourly.csv`,
  now committed to git. Home Assistant history is perishable; anything not
  archived before it purges is unrecoverable.
- **Sensor diagnostics** in the report: bias/MAE/correlation of the local sensors
  against reference sources, and replica-vs-production agreement.
- **Ground-truth agreement**: Cohen's kappa between Open-Meteo, Meteostat and
  Yandex, plus every model re-scored against the Meteostat label. The two
  sources agree only moderately (κ = 0.495), so part of each model's error
  belongs to the yardstick.

### Fixed

- **Analysis window is now clipped** (`build_grid(start=, end=)`). The grid spanned
  the union of all source timespans, so a 43-day Yandex archive stretched a 7-day
  run into a mostly-empty 43-day grid — HA coverage read 16.4%, which is 7/43.
- **Hourly grid** (was 10-minute). Ground truth is hourly, so five of every six
  rows could never carry a label and reported coverage could not exceed 16.7%.
  The permanent "low ground truth coverage" warning was an artifact of this.
- **Forward-fill limit is now measured in time, not rows.** The limit was computed
  in grid periods but applied to the union of source and grid timestamps, where
  each sensor is NaN at every other sensor's timestamps. On an hourly grid it
  worked out to 1 row, so a sensor reporting every 12 minutes reached only 28 of
  235 grid hours.
- **`ha_live` replica now reads `sensor.outside_dew_point_spread_trend`**, the
  input the deployed template actually uses, instead of a Python-recomputed 3h
  derivative. The two agree only at corr 0.83, which held the replica's peak
  score below the 50% alert threshold: it scored F1 0.000 against a live sensor
  scoring 0.143. Agreement with production is now corr 0.998, MAE 0.19.
- **Base rate is reported over labelled hours**, not the whole grid — 17 rain
  hours out of 192 labelled (8.9%) was being displayed as 1.5%.
- **Meteostat requests are chunked** to the API's 30-day limit. Longer ranges
  returned an error that the pipeline swallowed, silently dropping the source.
- **Pressure is compared against Open-Meteo `surface_pressure`**, not Meteostat's
  sea-level-reduced `pres` — differencing those reported Minsk's ~220 m elevation
  as a ~26 hPa sensor bias.
- **`pressure_variants` import no longer depends on `sys.path`**, which had left
  all five pressure models registered but failing when called.
- Models with no scored samples render as "no data" rather than 0.000.
- The "Data Context" block was emitted four times per report; now once.

### Changed

- Open-Meteo fetches now include `surface_pressure` and `dew_point_2m`.

## 2026-07-18

### Fixed

- **Precipitation forward-fill removed** (`rainlib.py::build_grid()`). Previously, precipitation columns were forward-filled during grid construction, inflating rain-hour counts by approximately 80%. The fix restricts forward-fill to temperature/humidity/pressure columns only.
- See [DATA_SOURCES.md](DATA_SOURCES.md) for updated forward-fill behavior description.
