# Changelog

Notable changes to rain-analysis.

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
