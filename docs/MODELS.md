# MODELS.md — Rain Prediction Models

Complete documentation of all rain prediction models in this analysis framework.

## Model Comparison Table

| Model | Type | F1 (7d) | Precision | Recall | Status |
|-------|------|:-------:|:---------:|:------:|--------|
| **ha_live** | Production | **0.484** | 0.519 | 0.455 | ✅ Best |
| **original** | Baseline v0.1 | 0.440 | 0.507 | 0.389 | 📊 Reference |
| **tuned** | Optimized | 0.441 | 0.448 | 0.433 | 🔧 Experimental |
| **trend_dominant** | Experimental | 0.115 | 0.696 | 0.063 | ❌ Failed |
| **pressure_aware** | Experimental | 0.440 | 0.507 | 0.389 | 🔧 Testing |
| **pressure_absolute** | Experimental | 0.190 | 0.165 | 0.226 | 🔧 Testing |
| **pressure_long_window** | Experimental | 0.198 | 0.176 | 0.226 | 🔧 Testing |
| **pressure_lagged** | Experimental | 0.196 | 0.173 | 0.226 | 🔧 Testing |
| **pressure_combined** | Experimental | 0.194 | 0.170 | 0.226 | 🔧 Testing |

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
# Proximity: 0°C spread = 100%, 10°C+ spread = 0%
proximity = clamp(100.0 - (spread / proximity_divisor * 100.0), 0, 100)
# Trend: narrowing spread (negative spread_deriv) boosts score
trend_score = clamp(-spread_deriv * trend_gain, -40, 40)
# Weighted blend (not additive) — both components contribute independently
rain_probability = clamp(proximity * 0.7 + trend_score * 0.7, 0, 100)
if rain_probability >= threshold:
    rain_alert = True
```

> **Note:** The original v0.1 model uses hardcoded constants (divisor=10, gain=20,
> weights=0.7, trend bounds=[-40, 40]) rather than `ModelParams`. This was fixed
> in PR #58 to make parameter tuning meaningful. When no params are provided,
> the v0.1 defaults are used for backward compatibility.

### Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `proximity_divisor` | 10 | Spread that maps to 0% proximity (°C) |
| `trend_gain` | 20 | Points per °C/h of spread narrowing |
| `trend_bounds` | [-40, 40] | Clamp on trend contribution |
| `blend_weights` | [0.7, 0.7] | Proximity and trend blend weights |
| `decision_threshold` | 50% | Rain/no-rain cutoff |

### How It Works

1. **Proximity score** — measures how close current conditions are to saturation
   - Small spread (T ≈ Td) → high proximity → rain likely
   - Large spread (dry air) → low proximity → no rain
   
2. **Trend reinforcement** — spread narrowing rate (°C/h)
   - Spread closing fast (negative `spread_deriv`) → positive trend score → boosts probability
   - Spread widening (positive `spread_deriv`) → negative trend score → suppresses probability
   - Both components clamped: `trend_score ∈ [-40, 40]`, `proximity ∈ [0, 100]`

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

## Pressure-Aware Models (✅ Implemented)

### 5. pressure_aware (Baseline Pressure Model)

**Status:** ✅ Implemented  
**Implementation:** `rainlib.py::model_pressure_aware`  
**Goal:** Add barometric pressure to eliminate dry-night false positives

#### Algorithm

Adds atmospheric pressure tendency as a third predictive factor:
- **Falling pressure** → approaching cyclone/storm → boosts rain probability
- **Rising pressure** → clearing weather → suppresses rain probability
- **Stable pressure** → no pressure signal → behaves like tuned model

```python
proximity = clamp(100 - spread / proximity_divisor * 100, 0, 100)
trend_score = clamp(-spread_deriv * trend_gain, trend_floor, trend_ceiling)

# Pressure derivative score — falling pressure adds, rising subtracts
pressure_change = derivative(pressure, window=pressure_window)
if abs(pressure_change) < abs(pressure_drop_threshold):
    pressure_score = 0.0    # no signal — stable pressure
else:
    pressure_score = clamp(-pressure_change * pressure_gain,
                           pressure_floor, pressure_ceiling)

# Weighted blend with hysteresis
raw = proximity * proximity_weight + trend_score * trend_weight + pressure_score * pressure_weight
result = hysteretic_decay(raw)  # rise instantly, decay slowly
```

#### Parameters

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `pressure_weight` | 0.35 | Weight of pressure in blend |
| `pressure_gain` | 25.0 | Multiplier for pressure change rate |
| `pressure_floor` | -15.0 | Max suppression from rising pressure |
| `pressure_ceiling` | 35.0 | Max boost from falling pressure |
| `pressure_window` | "3h" | Time window for derivative |
| `pressure_drop_threshold` | -0.5 | Minimum hPa/h to activate signal |

#### Key Design Decision: Weighted Blend + Hysteresis (not additive)

The actual implementation uses a **weighted blend** with hysteresis, NOT the originally proposed additive formula (`proximity + trend + pressure_factor`). This was chosen because:
1. **Weighted blend** allows independent tuning of each signal's contribution
2. **Hysteresis** prevents the score from crashing when pressure briefly rises mid-storm
3. The additive approach created excessive noise when pressure was fluctuating

---

### 5b. pressure_absolute (Variant A)

**Status:** 🔧 Testing  
**Implementation:** `pressure_variants.py::model_pressure_absolute`

**Hypothesis:** Low absolute pressure (<1000 hPa) is itself a rain indicator, even when pressure is currently rising (cyclone recovery).

Adds absolute pressure bonus to the pressure derivative signal:
- < 990 hPa: +20 bonus (deep cyclone)
- < 1000 hPa: +10 bonus (low pressure system)
- < 1005 hPa: +5 bonus (slightly low)

---

### 5c. pressure_long_window (Variant B)

**Status:** 🔧 Testing  
**Implementation:** `pressure_variants.py::model_pressure_long_window`

**Hypothesis:** 3h is too short to catch slow pressure changes preceding weather systems. Uses a 12h window with relaxed threshold (0.1 hPa/h).

---

### 5d. pressure_lagged (Variant C)

**Status:** 🔧 Testing  
**Implementation:** `pressure_variants.py::model_pressure_lagged`

**Hypothesis:** Pressure changes 6 hours ago predict rain now. Uses pressure lagged by 6h for derivative calculation, accounting for storm travel time.

---

### 5e. pressure_combined (Variant D)

**Status:** 🔧 Testing  
**Implementation:** `pressure_variants.py::model_pressure_combined`

**Hypothesis:** Multiple pressure signals together work better than any single one. Combines: 12h long window + 3h lagged short window + absolute pressure bonus.

---

## Future Models (Planned)

### 6. ensemble_vote (Future)## Performance Benchmarks

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

**Last Updated:** 2026-07-16  
**Maintainer:** Karasik (AI assistant for Kickoman/rain-analysis)
