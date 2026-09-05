# Changelog

Notable changes to rain-analysis.

## 2026-09-04

The daily reports stopped after 2026-08-22 when the runner that produced them
stopped; 2026-08-16..08-20 were missing too. Both gaps are filled, and the
report pipeline no longer needs Home Assistant to be reachable.

### Added

- **`scripts_utils/pull_measurements.py`** — the mirror of `push_measurements.py`.
  Reads sensor history back out of the backend (`GET /api/v1/data/measurements`)
  into the `entity_id,state,last_changed` CSV the analysis pipeline already
  understands, so `archive_ha_data.py` can fold it into `data/archive/ha_hourly.csv`.
  It requests one sensor per call — the endpoint pages over the combined row
  stream, so a multi-sensor request silently truncates — and treats a sensor that
  returns no rows as an error rather than letting a sensor-free report through.
  This is what makes the backend, rather than a live HA, the source of local
  history: `data/archive/ha_hourly.csv` now carries all six entities, including
  `sensor.rain_probability` and `sensor.outside_dew_point_spread`, which it had
  never held before.
- **`backfill_reports.py` takes its inputs as arguments** (`--ha-csv`,
  `--om-sources`, `--meteostat`, `--yandex-dir`, `--provenance`) instead of
  hardcoding the three archive paths, so a backfill from different sources does
  not require editing the script — and can include Yandex, which earlier
  backfills had to omit.

### Fixed

- **Overlapping Open-Meteo sources had arbitrary precedence.** `load_data`
  concatenated every `--om-sources` file, sorted, and kept the last row per
  timestamp — which only means "the last file on the command line" if the sort
  is stable. It was `quicksort`, so on overlapping hours the ground truth came
  partly from each file: passing the ERA5 archive and the forecast series
  together produced 9 rain hours in a window where the intended source had 6.
  Now sorted with `kind="stable"`.

### Note on ground truth

The new reports (2026-08-16 onward) take Open-Meteo precipitation from the
forecast API's past-days series — the same series the backend stores as
`openmeteo.precipitation`, and the one the 2026-08-14..08-22 reports already
used. Reports up to 2026-08-13 use the ERA5 archive series, which reports about
three times as many rain hours over the same period (52 vs 15 over
2026-08-24..09-03). Rain base rates are not comparable across that boundary,
and neither are scores that depend on them. Each backfilled report says so in
its provenance note.

## 2026-08-21 (evening)

The daily report for 2026-08-21 was regenerated after verification found its
multi-window and front sections resting on starved data, and a new model was
added for the project's actual question.

### Fixed

- **The daily pipeline now feeds on the durable archive.** `run_full_analysis.py`
  fetched Home Assistant history from the recorder alone, which purges after
  ~10 days — so the "14d" and "28d" windows of every daily report were the same
  ~9-day window twice (the 2026-08-21 report shipped with those columns
  byte-identical), and in the front section models were scored on ~190 of 581
  dry hours while the baselines saw all 581. The pipeline now fetches long-term
  statistics, folds them into `data/archive/ha_hourly.csv`, and merges archive +
  statistics + recorder before analysis. Verified effect: front AUCs claimed as
  0.64–0.77 on the starved window measure 0.48–0.62 with full coverage.
- **The front table shows per-candidate coverage** ("dry hours seen", with a ⚠️
  when a candidate saw well under the window's dry hours), so a starved model
  can no longer outrank a fully-scored one unnoticed.
- **`load_ha_csv` accepts mixed timestamp formats** (hourly statistics carry no
  microseconds, recorder rows do; pandas' single-format inference refused the
  merge).
- **`rainlib` package re-exports `label_front_within` / `detect_onsets`** —
  the front API existed only on the inner module.

### Added

- **`onset_gate`** (`pressure_variants.py::model_onset_gate`) — the first model
  aimed at the project's stated goal: from a dry hour, will rain *begin* within
  3 hours? A frozen four-term logistic (pressure anomaly, fall-from-24h-peak,
  RH, 3-hour temperature trend — deliberately no spread terms, which are
  anti-correlated with onsets) fitted once on 2021–2025 reanalysis. Held-out
  front-3h ROC AUC: 0.706 on 2025–26 reanalysis, 0.739 on local sensors, versus
  0.48–0.61 for every other registered model. On the regenerated 2026-08-21
  report it leads the front section, catching 15 of 18 onsets.


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
