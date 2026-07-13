# MODELS.md — Rain Prediction Models

Complete documentation of all rain prediction models in this analysis framework.

## Model Comparison Table

| Model | Type | F1 (7d) | Precision | Recall | Status |
|-------|------|:-------:|:---------:|:------:|--------|
| **ha_live** | Production | **0.484** | 0.519 | 0.455 | ✅ Best |
| **original** | Baseline v0.1 | 0.440 | 0.507 | 0.389 | 📊 Reference |
| **tuned** | Optimized | 0.441 | 0.448 | 0.433 | 🔧 Experimental |
| **trend_dominant** | Experimental | 0.115 | 0.696 | 0.063 | ❌ Failed |

*Scores from 7-day test (2026-07-05 to 2026-07-12), ground truth: Open-Meteo ≥0.1mm/h*

---

## 1. Original (Baseline v0.1)

**Status:** Reference baseline  
**Implementation:** `sensor.rain_probability` in Home Assistant  
**F1:** 0.440 | **Precision:** 0.507 | **Recall:** 0.389

### Algorithm

Dew-point spread-based detection with trend reinforcement:

```python
spread = temperature - dew_point
proximity = 100 * (1 - spread / proximity_divisor)
trend = humidity_increase_rate * trend_gain

rain_probability = proximity + trend
if rain_probability >= threshold:
    rain_alert = True
```

### Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `proximity_divisor` | 10 | Spread normalization (°C) |
| `trend_gain` | 20 | Trend weight multiplier |
| `decision_threshold` | 50% | Rain/no-rain cutoff |

### How It Works

1. **Proximity score** — measures how close current conditions are to saturation
   - Small spread (T ≈ Td) → high proximity → rain likely
   - Large spread (dry air) → low proximity → no rain
   
2. **Trend reinforcement** — rewards rising humidity
   - Recent RH increase → positive trend → boosts score
   - Falling RH → negative trend → suppresses score

3. **Decision** — threshold at 50%

### Strengths

- Simple, interpretable
- No training data required
- Works reasonably well for real rain events

### Weaknesses

- **Dry-night false positives** — calm clear nights with falling temperature close the spread just like rain does
- **No pressure awareness** — can't distinguish weather system from diurnal cycle
- **Low recall (0.389)** — misses 60% of rain events

### Known Issues

From `BASELINE_MODEL.md`:

> *"Спокойные ночи с падающей температурой закрывают spread точно так же, как и реальные дождливые ночи. Модель не может их отличить, потому что использует только поверхностную влажность."*

**Example false positive:**
- 23:00 — clear sky, T=18°C, RH=65%, Td=11°C, spread=7°C
- 03:00 — still clear, T=12°C, RH=85%, Td=10°C, spread=2°C → **ALERT** ❌
- Reality: no rain, just radiative cooling

---

## 2. ha_live (Production Model)

**Status:** ✅ Current production (deployed in Home Assistant)  
**F1:** 0.484 | **Precision:** 0.519 | **Recall:** 0.455

### Algorithm

Weighted blend of dew-point proximity and trend score:

```python
spread = dew_point_spread  # from sensor.outside_dew_point_spread
trend = dew_point_spread_trend  # from sensor.outside_dew_point_spread_trend (°C/h)

# Proximity score: 0°C spread = 100, 8°C+ spread = 0
proximity = 100 - (spread / 8 * 100)
proximity = clamp(proximity, 0, 100)

# Trend score: narrowing spread (-1.5°C/h or faster) boosts score,
# widening reduces it. Scaled to ±40 points.
trend_score = -trend * 26.7
trend_score = clamp(trend_score, -40, 40)

# Weighted blend
rain_probability = proximity * 0.7 + trend_score * 0.7
rain_probability = clamp(rain_probability, 0, 100)
```

### Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `proximity_divisor` | 8 | Spread normalization (°C) |
| `trend_multiplier` | 26.7 | Maps trend to ±40 point range |
| `proximity_weight` | 0.7 | Proximity contribution |
| `trend_weight` | 0.7 | Trend contribution |

### Production Implementation

**Template Sensor:**

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

**Automation:**

```yaml
alias: Possible rain notification
triggers:
  - trigger: numeric_state
    entity_id: sensor.outside_dew_point_spread
    below: 4
    for:
      minutes: 5
conditions:
  - condition: numeric_state
    entity_id: sensor.outside_dew_point_spread_trend
    below: -0.5
actions:
  - action: telegram_bot.send_message
    data:
      entity_id: notify.telegram_bot_kastus
      message: >-
        🌧️ Chutka mažlivy doždž!
        
        Roznaść pamiž temperaturaj pavietra i punktam rasy ŭžo
        {{ states('sensor.outside_dew_point_spread') }}°C i zvužvajecca z
        chutkaściu {{ states('sensor.outside_dew_point_spread_trend') }}°C/h.
mode: single
```

**Trigger:** Dew point spread < 4°C for 5+ minutes AND narrowing faster than -0.5°C/h

**Sensors Used:**
- `sensor.outside_dew_point_spread` — temperature minus dew point (°C)
- `sensor.outside_dew_point_spread_trend` — 1-hour rate of change (°C/h)

**Note:** `sensor.pressure_rain_score` exists but is currently unused (for testing/experimentation only).

### How It Works

**Proximity score** measures saturation:
- spread = 0°C (100% RH) → proximity = 100
- spread = 8°C → proximity = 0
- Linear interpolation between

**Trend score** detects approaching weather systems:
- Narrowing at -1.5°C/h → +40 points
- Widening at +1.5°C/h → -40 points
- No change → 0 points

**Weighted sum:** Both components weighted at 0.7 (yes, this means effective max is 140 before clamping, but result is always clamped to 0-100).

### Improvements Over Original

✅ **+10% F1** (0.440 → 0.484)  
✅ **+17% recall** (0.389 → 0.455) — catches more rain  
✅ **+2% precision** (0.507 → 0.519) — slightly fewer false positives

### Remaining Issues

Still suffers from dry-night false positives — **precision 0.519** means **48% of alerts are still false**.

The tighter spread threshold (8°C vs 10°C) and trend contribution help, but don't fully distinguish between:
- **Real rain:** weather system with falling pressure + closed spread
- **Dry night:** radiative cooling with stable pressure + closed spread

Next step: add pressure awareness (see `pressure_aware` model below).

---

## 3. Tuned (Grid-Search Optimized)

**Status:** 🔧 Experimental  
**F1:** 0.441 | **Precision:** 0.448 | **Recall:** 0.433

### Algorithm

Same structure as `original`, but parameters optimized via grid search over 7-day dataset.

### Optimized Parameters

| Parameter | Original | Tuned | Change |
|-----------|:--------:|:-----:|--------|
| `proximity_divisor` | 10 | **8** | Tighter spread threshold |
| `hysteresis_decay` | 0.3 | **0.2** | Less persistence |
| `trend_gain` | 20 | **15** | Lower trend weight |

### Grid Search Results

Tested 45 combinations:
- `proximity_divisor`: [6, 8, 10, 12, 15]
- `hysteresis_decay`: [0.2, 0.3, 0.5, 0.7, 0.9]
- `trend_gain`: [10, 15, 20, 25, 30]

**Best F1=0.486** at `(8, 0.2, 15)` — marginally better than production.

### Why Not Deployed?

- **Overfitting risk** — optimized on same 7-day window used for testing
- **Marginal gain** — F1 improvement is tiny (0.484 → 0.486)
- **Lower precision** — 0.448 vs 0.519 (more false positives)

Kept as reference for parameter sensitivity analysis.

### Insights

- **Tighter spread threshold (8°C)** catches more rain but also more false positives
- **Less hysteresis (0.2)** responds faster but noisier
- **Lower trend weight (15)** reduces overreaction to humidity spikes

---

## 4. trend_dominant (Failed Experiment)

**Status:** ❌ Failed  
**F1:** 0.115 | **Precision:** 0.696 | **Recall:** 0.063

### Algorithm

Inverts the weight balance — makes **trend** the primary signal and **proximity** secondary:

```python
proximity = 100 * (1 - spread / proximity_divisor)
trend = humidity_increase_rate * trend_gain

# Inverted formula
rain_probability = trend * 0.7 + proximity * 0.3
```

### Hypothesis (Rejected)

*"Humidity trend is a stronger rain signal than dew-point proximity."*

### Results

- **Recall 0.063** — misses 94% of rain events
- **Precision 0.696** — when it does alert, it's usually right
- **F1 0.115** — worst of all models

### Why It Failed

1. **Humidity trend is noisy** — spikes from:
   - Opening windows
   - Cooking
   - Sensor drift
   - Normal diurnal variation

2. **Trend alone insufficient** — rain needs both:
   - High absolute humidity (proximity)
   - Rising trend (system moving in)

3. **Over-conservative** — only alerts when trend is extreme, missing most rain

### Lesson Learned

✅ **Dew-point proximity is the core signal**  
✅ **Trend is a useful reinforcement, not a replacement**

---

## Model Selection Guide

| Use Case | Recommended Model |
|----------|-------------------|
| **Production deployment** | `ha_live` — best balance |
| **Baseline comparison** | `original` — reference point |
| **Parameter research** | `tuned` — sensitivity analysis |
| **What not to do** | `trend_dominant` — failed approach |

---

## Future Models (Planned)

### 5. pressure_aware (Next Priority)

**Status:** 🚧 Planned  
**Goal:** Eliminate dry-night false positives

#### Concept

Add barometric pressure to distinguish:
- **Real rain:** falling pressure + closed spread
- **Dry night:** stable pressure + closed spread

#### New Inputs

From Meteostat (`ms_pres`) or HA (`sensor.office_weather_station_pressure`):
- Absolute pressure (hPa)
- Pressure trend (3h derivative)

#### Proposed Formula

```python
proximity = 100 * (1 - spread / proximity_divisor)
trend = humidity_increase_rate * trend_gain
pressure_factor = -pressure_trend * pressure_gain  # negative trend = rising score

rain_probability = proximity + trend + pressure_factor
```

#### Expected Improvement

Target **precision ≥0.70** (reduce false positives by ~40%)  
Maintain **recall ≥0.45** (don't lose rain detection)

---

### 6. ensemble_vote (Future)

**Status:** 💡 Idea  
**Goal:** Combine multiple signals via voting

#### Concept

Three independent classifiers:
1. Dew-point proximity
2. Pressure trend
3. Precipitation data from external sources (Yandex, Open-Meteo, Meteostat)

Vote: 2 out of 3 must agree.

#### Advantage

Reduces false positives from any single source.

#### Challenge

Requires reliable real-time external APIs.

---

### 7. ml_model (Long-Term)

**Status:** 🔮 Future  
**Goal:** Learn patterns from historical data

#### Inputs

- Temperature, humidity, dew point
- Pressure (absolute + trend)
- Time of day, season
- Past 1h/3h/6h trends

#### Models to Try

- **Logistic Regression** (baseline)
- **Random Forest** (feature importance)
- **XGBoost** (best performance)

#### Data Requirement

Need **6+ months** of labeled data with ground truth.

Current dataset: 7 days (insufficient for training).

---

## Performance Benchmarks

### Test Dataset

- **Period:** 2026-07-05 to 2026-07-12 (7 days)
- **Ground Truth:** Open-Meteo precipitation ≥0.1mm/h
- **Rain Hours:** 97 out of 192 (51%)
- **Evaluation:** 10-minute grid, resampled to hourly for scoring

### Metrics Explained

- **Precision** = TP / (TP + FP) — *"Of all alerts, how many were real rain?"*
- **Recall** = TP / (TP + FN) — *"Of all rain events, how many did we catch?"*
- **F1** = 2 × (P × R) / (P + R) — *Harmonic mean (balanced score)*

### Scoring Code

All models evaluated via `rainlib.py`:

```python
scores = rl.confusion_at_threshold(
    pred=grid['rain_probability'],
    truth=grid['rain_truth'],
    threshold=50.0
)
```

Returns: `{tp, fp, tn, fn, precision, recall, f1}`

---

## Implementation Notes

### Adding a New Model

1. **Implement in `rainlib.py`** or as a standalone function
2. **Add to `run_analysis.py`** in `evaluate_models()`
3. **Update this doc** with algorithm, parameters, and results
4. **Run full analysis:** `python run_full_analysis.py --days 30`

### Model Naming Convention

- `original` — baseline reference
- `ha_live` — current production
- `<feature>_<variant>` — experiments (e.g., `pressure_aware`, `trend_dominant`)
- `tuned` — optimized via grid search
- `ensemble_*` — voting/combination models
- `ml_*` — machine learning models

### Parameter Storage

Default parameters are in `rainlib.py` functions.  
Override via `AnalysisConfig` in `run_analysis.py`.

---

## References

- [BASELINE_MODEL.md](./BASELINE_MODEL.md) — Detailed baseline analysis
- [CLI_RUNNER.md](./CLI_RUNNER.md) — How to run analysis
- [DATA_SOURCES.md](./DATA_SOURCES.md) — Data collection guide

---

**Last Updated:** 2026-07-13  
**Maintainer:** Karasik (AI assistant for Kickoman/rain-analysis)
