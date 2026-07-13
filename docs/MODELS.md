# Rain Prediction Models

This document describes the rain prediction models used in this project, from simple baseline to production-ready implementations.

---

## 1. original (Baseline)

**Status:** 🧪 Experimental baseline  
**F1:** 0.440 | **Precision:** 0.507 | **Recall:** 0.389

### Algorithm

Simple linear combination of two weather signals:

```python
# Proximity to dew point (0-100 scale)
proximity = 100 * (1 - spread / proximity_divisor)

# Humidity increase rate (how fast RH rising)
trend = humidity_increase_rate * trend_gain

# Combined score
rain_probability = proximity + trend
```

### Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `proximity_divisor` | 10 | Spread scaling (10°C = 0% rain chance) |
| `trend_gain` | 20 | Trend weight (1%/min rise = 20 points) |
| `decision_threshold` | 50% | Rain/no-rain cutoff |

### How It Works

**Proximity:** Temperature approaching dew point signals condensation risk.  
**Trend:** Rising humidity suggests moisture inflow (fronts, convection).

Both indicators together improve accuracy over using spread alone.

### Weakness

❌ **Dry-night false positives** — radiative cooling at night causes spread to narrow even when no rain is coming.

**Example false positive:**
- 23:00 — clear sky, T=18°C, RH=65%, Td=11°C, spread=7°C
- 03:00 — still clear, T=12°C, RH=85%, Td=10°C, spread=2°C → **ALERT** ❌
- Reality: no rain, just radiative cooling

---

## 2. ha_live (Production Model)

**Status:** ✅ Current production (deployed in Home Assistant)  
**Performance:** Not yet benchmarked against validation dataset

### Algorithm

Weighted blend of proximity and trend scores with strict range clamping:

```python
# Proximity score: linear scale from 8°C spread (0%) to 0°C spread (100%)
proximity = 100 - (spread / 8.0 * 100)
proximity = max(0, min(100, proximity))

# Trend score: narrowing spread adds points, widening subtracts
# Scaled to ±40 points range
trend_score = -trend * 26.7
trend_score = max(-40, min(40, trend_score))

# Weighted blend (both weighted at 0.7)
total = (proximity * 0.7) + (trend_score * 0.7)
rain_probability = max(0, min(100, total))
```

### Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `spread_divisor` | 8 | Spread scaling (8°C = 0%, 0°C = 100%) |
| `trend_multiplier` | 26.7 | Trend weight (-1.5°C/h → +40 points) |
| `proximity_weight` | 0.7 | Proximity contribution |
| `trend_weight` | 0.7 | Trend contribution |
| `trend_range` | ±40 | Trend score bounds |

### Production Setup

**Template Sensor:** `sensor.rain_probability`

Updates every 15-30 minutes based on:
- `sensor.outside_dew_point_spread` — current spread (°C)
- `sensor.outside_dew_point_spread_trend` — rate of change (°C/h)

**Automation:** `automation.possible_rain_notification`

Triggers when:
1. Spread drops below 4°C for 5+ minutes
2. AND trend < -0.5°C/h (narrowing)

Action: Sends Telegram notification

**Note:** `sensor.pressure_rain_score` exists but is not currently used in production — it's for testing purposes only.

### Home Assistant Configuration

<details>
<summary>Template Sensor (rain_probability)</summary>

```jinja
{% set spread = states('sensor.outside_dew_point_spread') | float(10) %}
{% set trend = states('sensor.outside_dew_point_spread_trend') | float(0) %}

{# Proximity score: 0°C spread = 100, 8°C+ spread = 0 #}
{% set proximity = (100 - (spread / 8 * 100)) | round(0) %}
{% set proximity = [proximity, 0] | max %}
{% set proximity = [proximity, 100] | min %}

{# Trend score: narrowing fast (-1.5°C/h or more) boosts score,
   widening reduces it. Scaled to +/-40 points. #}
{% set trend_score = (-trend * 26.7) | round(0) %}
{% set trend_score = [trend_score, -40] | max %}
{% set trend_score = [trend_score, 40] | min %}

{# Weighted blend: proximity matters more than trend #}
{% set total = (proximity * 0.7) + (trend_score * 0.7) %}
{% set total = [total, 0] | max %}
{% set total = [total, 100] | min %}
{{ total | round(0) }}
```

</details>

<details>
<summary>Automation (possible_rain_notification)</summary>

```yaml
alias: Possible rain notification
description: ""
triggers:
  - trigger: numeric_state
    entity_id:
      - sensor.outside_dew_point_spread
    for:
      hours: 0
      minutes: 5
      seconds: 0
    below: 4
conditions:
  - condition: numeric_state
    entity_id: sensor.outside_dew_point_spread_trend
    below: -0.5
actions:
  - action: telegram_bot.send_message
    metadata: {}
    data:
      entity_id:
        - notify.telegram_bot_kastus
      message: >-
        🌧️ Chutka mažlivy doždž!

        Roznaść pamiž temperaturaj pavietra i punktam rasy ŭžo {{
        states('sensor.outside_dew_point_spread') }}°C i zvužvajecca z
        chutkaściu {{ states('sensor.outside_dew_point_spread_trend') }}°C/h.
mode: single
```

</details>

### Design Notes

**Why both weights are 0.7?**  
This effectively makes the total score: `0.7 * (proximity + trend_score)`. The dual weighting appears to be a scaling factor rather than differential weighting between the two components.

**Why trend_multiplier = 26.7?**  
This gives approximately ±40 points for realistic trend ranges:
- Fast narrowing (-1.5°C/h) → +40 points
- Fast widening (+1.5°C/h) → -40 points

**No hysteresis:**  
Unlike documented earlier versions, the production model has no state persistence. Each calculation is independent.

### Improvements Over Original

✅ More sensitive to rapid changes (stronger trend component)  
✅ Stricter range bounds prevent score overflow  
✅ Production-tested automation thresholds

### Remaining Gaps

⚠️ **Performance unknown** — F1/precision/recall not yet measured against validation dataset  
⚠️ **Still vulnerable to dry-night false positives** — no atmospheric stability correction  
⚠️ **Pressure signals unused** — `pressure_rain_score` available but not integrated

---

## 3. pressure_based (Experimental)

**Status:** 🧪 Under development  
**F1:** Not yet evaluated

### Algorithm

Uses barometric pressure trends to distinguish frontal systems from radiative effects:

```python
# Pressure drop score (falling pressure = weather system approaching)
pressure_score = -pressure_trend * pressure_gain

# Combine with dew point signals
rain_probability = proximity + trend + pressure_score
```

### Rationale

Radiative cooling causes spread narrowing **without** pressure changes.  
Real weather systems cause spread narrowing **with** falling pressure.

This should reduce dry-night false positives.

### Status

Pressure sensor exists in Home Assistant (`sensor.pressure_rain_score`) but algorithm not yet finalized or validated.

---

## Future Work

### Short Term
1. **Benchmark `ha_live`** — measure F1/precision/recall on validation dataset
2. **Document actual vs claimed performance** — current docs claim 0.484 F1 but this may be from an older version

### Medium Term
1. **Integrate pressure signals** — reduce false positives from radiative cooling
2. **Add temporal filtering** — real rain events last 30+ minutes, transient spikes don't
3. **Retrain with ensemble approach** — combine multiple data sources (Open-Meteo, Yandex, etc.)

### Long Term
1. **Machine learning model** — explore XGBoost/neural networks for nonlinear patterns
2. **Validation against radar** — compare predictions to actual precipitation (if data available)
3. **Location-specific tuning** — parameters may need adjustment for different climates

---

## Model Comparison

| Model | F1 | Precision | Recall | Status | Notes |
|-------|-----|-----------|--------|--------|-------|
| `original` | 0.440 | 0.507 | 0.389 | Baseline | Simple, interpretable |
| `ha_live` | TBD | TBD | TBD | Production | Needs benchmarking |
| `pressure_based` | TBD | TBD | TBD | Experimental | Pressure integration incomplete |

**Evaluation dataset:** Historical weather data with ground-truth rain labels from local observations.

---

## References

- **Dew point theory:** [National Weather Service](https://www.weather.gov/lmk/humidity)
- **Rain prediction basics:** [Met Office guide](https://www.metoffice.gov.uk/weather/learn-about/weather/how-weather-works)
- **Barometric pressure and weather:** [NOAA primer](https://www.weather.gov/jetstream/pressure)
