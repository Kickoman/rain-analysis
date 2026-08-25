# Home Assistant → Backend Integration

How sensor readings flow from Home Assistant into the backend's
measurements API (`POST /api/v1/data/measurements`).

Design (decided in the umbrella issue #221 and session decisions of
2026-08-25): **HA pushes, the backend never reaches into the home network.**
An HA automation fires on every state change of the tracked sensors and
POSTs the new value with a write-scoped API key. Browsers then poll
`GET /api/v1/data/current` for the latest values.

## 1. Create a write-scoped API key

On the backend host:

```bash
cd backend
python scripts/create_admin_key.py            # once, to get an admin key
curl -X POST https://BACKEND_HOST/api/v1/admin/keys \
  -H "X-API-Key: <admin key>" \
  -H "Content-Type: application/json" \
  -d '{"owner": "home-assistant", "description": "HA push automation",
       "scope": "write", "environment": "live",
       "rate_limit_rpm": 60, "rate_limit_rph": 2000, "rate_limit_rpd": 20000}'
```

Store the returned key in HA's `secrets.yaml`:

```yaml
rain_backend_write_key: ra_live_...
```

## 2. configuration.yaml — rest_command

```yaml
rest_command:
  push_rain_measurement:
    url: "https://BACKEND_HOST/api/v1/data/measurements"
    method: POST
    headers:
      X-API-Key: !secret rain_backend_write_key
      Content-Type: application/json
    payload: >
      {"source": "ha",
       "measurements": [
         {"sensor": "{{ entity }}",
          "timestamp": "{{ now().astimezone().isoformat() }}",
          "value": "{{ states(entity) }}"}
       ]}
```

## 3. automations.yaml — push on state change

The tracked set matches the model-input entities used by the analysis
pipeline (`scripts_utils/fetch_ha_data.py` defaults):

```yaml
- alias: "Push rain sensors to backend"
  id: push_rain_sensors_to_backend
  mode: queued
  max: 25
  trigger:
    - platform: state
      entity_id:
        - sensor.rain_probability
        - sensor.datchik_klimata_temperatura
        - sensor.datchik_klimata_vlazhnost
        - sensor.filtered_pressure
  condition:
    - condition: template
      value_template: >
        {{ trigger.to_state is not none
           and trigger.to_state.state not in ['unknown', 'unavailable', ''] }}
  action:
    - service: rest_command.push_rain_measurement
      data:
        entity: "{{ trigger.entity_id }}"
```

Notes:

- `mode: queued` keeps rapid state changes from cancelling each other.
- The backend also rejects `unknown`/`unavailable` rows server-side, so the
  condition is a bandwidth optimisation, not the safety net.
- The ingest endpoint upserts on (sensor, timestamp) — duplicate deliveries
  after an HA restart are harmless.

## 4. Gaps and backfill

`rest_command` has no retry. If the backend was unreachable, the missed
interval is repaired from HA's recorder history (retention ~10 days) with:

```bash
RAIN_BACKEND_KEY=ra_live_... python scripts_utils/push_measurements.py \
  --backend-url https://BACKEND_HOST --from-ha --days 2
```

The same script does the initial backfill from the committed archive:

```bash
RAIN_BACKEND_KEY=ra_live_... python scripts_utils/push_measurements.py \
  --backend-url https://BACKEND_HOST --from-csv data/archive/ha_hourly.csv
```

Both are idempotent — re-running them never duplicates rows.

## 5. Ground truth

The daily pipeline pushes Open-Meteo precipitation as the sensor
`openmeteo.precipitation` (unit mm) through the same ingest endpoint; the
backend's metrics calculator reads it back as the rain ground truth. The
backend itself makes no outbound HTTP requests.
