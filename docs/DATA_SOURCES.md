# Data Sources & Fetching

How to obtain all three data sources required for the rain analysis pipeline.

## Overview

The analysis pipeline needs four data sources aligned on one time grid:

| Source | What | Format | How to get |
|--------|------|--------|------------|
| **Home Assistant** | Local sensors (temp, humidity, model output) | CSV | `fetch_ha_data.py` |
| **Open-Meteo** | Ground truth precipitation | JSON | `fetch_openmeteo.py` |
| **Meteostat** | Historical weather station data (incl. pressure!) | JSON | `fetch_meteostat.py` |
| **Yandex Weather** | Independent weather data for comparison | JSON archive | `fetch_yandex_archive.py` |

## 1. Home Assistant Data

### Required Sensors

```
sensor.datchik_klimata_temperatura  → outdoor temperature (°C)
sensor.datchik_klimata_vlazhnost    → outdoor humidity (%)
sensor.rain_probability             → live model probability (%)
```

### Fetch

```bash
python fetch_ha_data.py --days 7 --output data/ha.csv
```

### Output Format

```csv
entity_id,state,last_changed
sensor.datchik_klimata_temperatura,17.5,2026-07-05T19:25:05+00:00
sensor.datchik_klimata_vlazhnost,66,2026-07-05T19:25:05+00:00
...
```

See [HA_DATA_FETCHER.md](HA_DATA_FETCHER.md) for full details.

## 2. Open-Meteo Data (Ground Truth)

### Location

Minsk, Belarus: **53.930716, 27.596646**

### API

#### Current + Recent Past (recommended)

```bash
python fetch_openmeteo.py \
    --use-forecast \
    --days 7 \
    --output data/openmeteo.json
```

Uses [Open-Meteo Forecast API](https://open-meteo.com/en/docs) with `past_days` parameter.
Good for: recent data (past 7-92 days).

#### Historical Archive

```bash
python fetch_openmeteo.py \
    --start 2026-06-30 \
    --end 2026-07-06 \
    --output data/openmeteo.json
```

Uses [Open-Meteo Archive API](https://archive-api.open-meteo.com/v1/archive).
Good for: older data, exact date ranges.

> **Note:** If the Open-Meteo API times out, check network connectivity first.
> The Forecast API (`--use-forecast`) is a **different data source** — do NOT use it as
> a timeout fallback for archive data; the results may not be comparable.

### Manual Fetch (Curl)

```bash
# Forecast API (recent data + future)
curl "https://api.open-meteo.com/v1/forecast?\
latitude=53.930716&longitude=27.596646&\
hourly=temperature_2m,relative_humidity_2m,precipitation,rain,showers&\
timezone=UTC&past_days=7" \
-o data/openmeteo.json

# Archive API (historical)
curl "https://archive-api.open-meteo.com/v1/archive?\
latitude=53.930716&longitude=27.596646&\
start_date=2026-07-01&end_date=2026-07-07&\
hourly=temperature_2m,relative_humidity_2m,precipitation,rain,showers&\
timezone=UTC" \
-o data/openmeteo.json
```

### Output Format

```json
{
  "hourly": {
    "time": ["2026-07-01T00:00", "2026-07-01T01:00", ...],
    "temperature_2m": [20.5, 20.1, ...],
    "relative_humidity_2m": [72, 74, ...],
    "precipitation": [0.0, 0.0, 0.3, ...],
    "rain": [0.0, 0.0, 0.3, ...],
    "showers": [0.0, 0.0, 0.0, ...]
  },
  "utc_offset_seconds": 0,
  ...
}
```

> **Key field:** `precipitation` is the hourly total (mm) and serves as ground truth
> for `rain_truth` labelling.

### Multiple Files

You can collect multiple open-meteo responses over time and pass them all:

```bash
python run_analysis.py \
    --om-sources data/om_week1.json data/om_week2.json data/om_week3.json \
    ...
```

Rainlib concatenates them automatically, deduplicating on time.

## 3. Meteostat Data (Ground Truth #2 + Pressure)

### Location

Station 26850 — Minsk

### Fetch

```bash
python fetch_meteostat.py --days 7 --output data/meteostat.json
```

Uses [Meteostat API](https://dev.meteostat.net/api/) hourly station data.

### Output Format

```json
{
  "meta": { "station": { "id": "26850" } },
  "data": [
    {
      "time": "2026-07-05 00:00:00",
      "temp": 14.5,
      "rhum": 89.0,
      "prcp": 0.0,
      "pres": 1007.7,
      "dwpt": 12.9,
      "wdir": 320.0,
      "wspd": 7.0
    },
    ...
  ]
}
```

**Key fields in rainlib:**
- `ms_precip` — hourly precipitation (ground truth #2)
- `ms_pres` — atmospheric pressure (for pressure-aware model!)
- `ms_temp`, `ms_rhum` — temperature, humidity (cross-check)
- `ms_wspd`, `ms_wdir` — wind (future use)

### Why Meteostat?

Unlike Open-Meteo (reanalysis) and Yandex (spot observations), Meteostat provides:
- **Real weather station data** (station 26850 = Minsk)
- **Pressure data** — essential for pressure-aware model
- **Third vote** — can use majority voting for rain detection

## 4. Yandex Weather Data

### Archive Location

The Yandex data is collected hourly by a local process and served as an archive:

```
http://10.8.0.4:7005/weather.tgz
```

### Fetch & Extract

```bash
python fetch_yandex_archive.py --output data/yandex/
```

### Archive Structure

```
year/month/day/HHMMSS.json
```

Each JSON is a snapshot containing:
- `now` / `now_dt` — capture time
- `fact` — current weather observation:
  - `temp`, `feels_like`, `humidity` — basic weather
  - `condition` — weather condition (cloudy, rainy, overcast, etc.)
  - `prec_prob`, `prec_strength` — precipitation data
  - `pressure_mm`, `pressure_pa` — barometric pressure
  - `wind_speed`, `wind_dir`, `wind_gust` — wind data
- `forecasts` — hourly forecast for next ~24 hours

### Example Snapshot

```json
{
  "now": 1783879201,
  "fact": {
    "temp": 18,
    "humidity": 84,
    "condition": "cloudy",
    "feels_like": 17,
    "wind_speed": 3.9,
    "wind_dir": "nw",
    "pressure_mm": 740,
    "prec_prob": 0
  }
}
```

### How Rainlib Uses It

The `load_yandex_archive()` function in rainlib.py extracts:
- `yx_temp`, `yx_humidity`, `yx_feels_like` — temperature/humidity
- `yx_condition` — weather condition string
- `yx_prec_prob`, `yx_prec_strength` — precipitation data
- `yx_pressure_mm` — barometric pressure (useful for pressure-aware model!)
- `yx_is_rain` — binary flag (1 if condition contains "rain")

## Pipeline Script (Putting It All Together)

```bash
#!/bin/bash
# collect_all_data.sh — fetch all three sources for analysis

DATE=$(date +%Y-%m-%d)
OUTDIR="data/${DATE}"
mkdir -p "${OUTDIR}"

echo "=== 1/3: Home Assistant ==="
python fetch_ha_data.py \
    --days 7 \
    --output "${OUTDIR}/ha.csv" \
    --quiet

echo "=== 2/3: Open-Meteo ==="
python fetch_openmeteo.py \
    --use-forecast \
    --days 7 \
    --output "${OUTDIR}/openmeteo.json" \
    --quiet

echo "=== 3/4: Open-Meteo ==="
python fetch_openmeteo.py \
    --use-forecast \
    --days 7 \
    --output "${OUTDIR}/openmeteo.json" \
    --quiet

echo "=== 4/4: Meteostat ==="
python fetch_meteostat.py \
    --days 7 \
    --output "${OUTDIR}/meteostat.json" \
    --quiet

echo "✓ All data collected in ${OUTDIR}/"

echo "=== Running Analysis ==="
python run_analysis.py \
    --ha-csv "${OUTDIR}/ha.csv" \
    --om-sources "${OUTDIR}/openmeteo.json" \
    --meteostat "${OUTDIR}/meteostat.json" \
    --yandex-dir "${OUTDIR}/yandex/" \
    --output "reports/${DATE}.json" \
    --plots
```

## Troubleshooting

### HA returns 401

- Token expired or invalid
- Check `~/.openclaw/workspace/.ha_config.json`
- Create new long-lived token in HA profile

### Open-Meteo timeout

- Network might be restricted on the analysis machine
- Try `--use-forecast` flag (different API endpoint)
- Try curl manually to check connectivity
- Pre-fetch the data on a machine with internet access

### Yandex archive not found

- Check that the hour-process is running: `curl -I http://10.8.0.4:7005/`
- Verify archive URL: `curl -s http://10.8.0.4:7005/weather.tgz | tar -tz | head`
- The archive regenerates hourly; wait for next cycle

### Missing data overlap

The analysis grid spans the earliest to latest timestamp across all sources.
If sensors were offline during a period, those columns will be NaN — 
rainlib handles this gracefully with forward-fill and NaN guards.
