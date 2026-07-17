# Home Assistant Data Fetcher

Script for exporting Home Assistant sensor history to CSV format required by `run_analysis.py`.

## Overview

`fetch_ha_data.py` queries the Home Assistant history API and exports sensor data
in the exact format expected by the rain analysis pipeline:

```csv
entity_id,state,last_changed
sensor.datchik_klimata_temperatura,17.5,2026-07-05T19:25:05+00:00
sensor.datchik_klimata_vlazhnost,66,2026-07-05T19:25:05+00:00
...
```

## Quick Start

```bash
python fetch_ha_data.py \
    --days 7 \
    --output data/ha_export.csv
```

This fetches the last 7 days of history for the default sensors:
- `sensor.datchik_klimata_temperatura` (outdoor temperature)
- `sensor.datchik_klimata_vlazhnost` (outdoor humidity)
- `sensor.rain_probability` (live model output)

## Arguments

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--config` | | `~/.homeassistant/ha_config.json` | Path to HA config (url + token) |
| `--entities` | | See above | Entity IDs to export (space-separated) |
| `--days` | | `7` | Number of days of history to fetch |
| `--start` | | — | Start time (ISO 8601, overrides `--days`) |
| `--end` | | now | End time (ISO 8601) |
| `--output`, `-o` | ✓ | — | Output CSV file path |
| `--quiet`, `-q` | | off | Suppress progress messages |

## Examples

### Last 7 days (default)

```bash
python fetch_ha_data.py --output data/ha_7d.csv
```

### Specific date range

```bash
python fetch_ha_data.py \
    --start 2026-07-01T00:00:00 \
    --end 2026-07-07T23:59:59 \
    --output data/ha_week.csv
```

### Custom entities

```bash
python fetch_ha_data.py \
    --entities sensor.temp_bedroom sensor.humidity_bedroom \
    --days 30 \
    --output data/ha_bedroom.csv
```

### Quiet mode (for automation)

```bash
python fetch_ha_data.py --days 7 --output data/ha.csv --quiet
```

## HA Config File

The script expects a JSON config file with:

```json
{
  "url": "http://10.8.0.4:8123",
  "token": "your_long_lived_access_token"
}
```

Default location: `~/.homeassistant/ha_config.json`

To create a long-lived access token:
1. Go to your HA profile → "Long-Lived Access Tokens"
2. Click "Create Token"
3. Copy the token and save it in the config file

## Integration with Analysis Pipeline

Once you have the CSV:

```bash
# 1. Fetch HA data
python fetch_ha_data.py --days 7 --output data/ha.csv

# 2. Run analysis
python run_analysis.py \
    --ha-csv data/ha.csv \
    --om-sources data/openmeteo.json \
    --output analysis_report.json
```

## Output Format

The CSV has exactly three columns:
- `entity_id` — Home Assistant entity ID
- `state` — sensor value (numeric or string)
- `last_changed` — ISO 8601 timestamp with timezone

Records are sorted by timestamp (ascending).

Invalid/unavailable states are filtered out automatically.

## Automated Fetching

For regular analysis runs, fetch fresh data on schedule:

```bash
#!/bin/bash
# daily_analysis.sh

DATE=$(date +%Y-%m-%d)

# Fetch last 7 days of HA data
python fetch_ha_data.py \
    --days 7 \
    --output "data/ha_${DATE}.csv" \
    --quiet

# Run analysis
python run_analysis.py \
    --ha-csv "data/ha_${DATE}.csv" \
    --om-sources data/openmeteo.json \
    --output "reports/${DATE}.json" \
    --quiet
```

## Troubleshooting

### 401 Unauthorized

- Check that your token is valid (not expired)
- Verify the token has the right permissions
- Test with: `curl -H "Authorization: Bearer YOUR_TOKEN" http://YOUR_HA/api/`

### No data returned

- Check that the entity IDs are correct
- Verify the time range covers when the sensors were active
- Look at HA Logbook to see if the sensors reported during that period

### Timeout errors

- Large date ranges (>30 days) can take time
- Consider fetching in smaller chunks
- Increase timeout in the script if needed
