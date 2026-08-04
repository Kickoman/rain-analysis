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
| **combined** | Experimental | TBD | TBD | TBD | 🔧 Testing |

*Scores from 7-day test (2026-07-05 to 2026-07-12), ground truth: Open-Meteo ≥0.1mm/h*

> ⚠️ **Caveat:** These benchmarks predate the 2026-07-18 precipitation forward-fill bugfix. Pre-fix, rain-hour counts were inflated ~80%. Post-fix numbers may differ. See [CHANGELOG.md](CHANGELOG.md) for details.

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

#### Weight Interpretation

⚠️ **Important:** Weights in this model are **amplification coefficients**, not normalized probabilities.

- **Sum of weights:** 0.7 + 0.7 = **1.4** (not 1.0)
- Each signal is multiplied by its weight and then summed
- The total can exceed 100 before the final clamp to [0, 100]
- Higher weight = stronger influence on the final score

**Example calculation:**

```python
# Scenario: humid conditions with rapid spread narrowing
proximity = 70.0       # spread = 2.4°C
trend_score = 40.0     # narrowing at -1.5°C/h

# Raw calculation (before clamp)
raw = proximity * 0.7 + trend_score * 0.7
    = 70 * 0.7 + 40 * 0.7
    = 49 + 28
    = 77

# Final result (after clamp to [0, 100])
result = clamp(77, 0, 100) = 77%
```

**Why not normalized to 1.0?**
- The model uses **amplification** rather than **averaging**
- Each signal contributes independently to boost the score
- Clamping to [0, 100] at the end ensures a valid probability range

This is intentional design, not an error. The weights control relative influence, not probability distribution.

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

Same structure as `model_tuned()` in `rainlib.py` — stateful model with hysteresis and dryness ceiling. Uses `ModelParams` defaults.

### Actual Parameters (from `ModelParams` defaults)

| Parameter | Value | Purpose |
|-----------|:------|---------|
| `proximity_divisor` | 7.0 | Spread that maps to 0% proximity (°C) |
| `hysteresis_decay` | 0.30 | Decay rate toward new lower value |
| `trend_gain` | 20.0 | Points per °C/h of spread narrowing |
| `trend_floor` | -15.0 | Max suppression from widening spread |
| `trend_ceiling` | 30.0 | Max boost from narrowing spread |
| `proximity_weight` | 0.8 | Proximity contribution weight |
| `trend_weight` | 0.5 | Trend contribution weight |
| `dry_spread_cutoff` | 10.0 | Above this spread, cap output |
| `dry_ceiling` | 40.0 | Maximum score when spread > cutoff |

### Implementation Notes

The actual `model_tuned()` function in `rainlib.py` uses `ModelParams()` defaults, **not** grid-search-optimized values. The name "tuned" is historical.

For details on grid search experiments (which found marginal improvements but were not deployed due to overfitting risk), see analysis notebooks.

### Why Not Deployed?

- **Overfitting risk** — optimized on same 7-day window used for testing
- **Marginal gain** — F1 improvement over `ha_live` was tiny
- **Lower precision** — 0.448 vs 0.519 (more false positives)

Kept as reference for parameter sensitivity analysis.

---

## 4. trend_dominant (Failed Experiment)

**Status:** ❌ Failed  
**F1:** 0.115 | **Precision:** 0.696 | **Recall:** 0.063

### Algorithm

**Trend-only model** gated by dry-spread ceiling, with stateful hysteresis. Does **not** use proximity as a weighted term — only as a gate.

```python
# Actual implementation from rainlib.py::model_trend_dominant
spread = dew_point_spread
deriv = spread_derivative  # °C/h

# Trend score (boosted gain: 1.5× normal)
trend_score = clamp(-deriv * trend_gain * 1.5, -20.0, 100.0)

# Dryness gate: if spread > dry_spread_cutoff, cap output
if spread < dry_spread_cutoff:
    ceiling = 100.0  # no limit
else:
    ceiling = dry_ceiling  # cap at ~40

# Apply ceiling
raw_score = min(trend_score, ceiling)

# Hysteresis: score rises instantly, decays slowly
result = hysteretic_decay(raw_score, previous_score, decay=hysteresis_decay)
```

### Key Difference from Documentation

**Old (incorrect) doc claimed:**
```python
rain_probability = trend * 0.7 + proximity * 0.3  # ❌ NOT what code does
```

**Actual logic:**
- Trend is the **only** signal
- Proximity acts as a **ceiling gate**, not a weighted term
- When spread is high (dry), trend score is capped at `dry_ceiling` (~40)
- When spread is low (humid), trend score can reach 100

### Parameters

| Parameter | Default | Used Value | Purpose |
|-----------|:-------:|:----------:|---------|
| `trend_gain` | 20.0 | **30.0** (1.5×) | Amplified trend sensitivity |
| `trend_bounds` | [-15, 30] | **[-20, 100]** | Wider range for trend-only model |
| `dry_spread_cutoff` | 10.0 | 10.0 | Spread above which ceiling applies |
| `dry_ceiling` | 40.0 | 40.0 | Max score when spread > cutoff |
| `hysteresis_decay` | 0.30 | 0.30 | Decay rate (0 = frozen, 1 = no memory) |

### Hypothesis (Rejected)

*"Humidity trend derivative is a stronger rain signal than absolute proximity."*

### Results

- **Recall 0.063** — misses 94% of rain events
- **Precision 0.696** — when it does alert, it's usually right (but rarely alerts)
- **F1 0.115** — worst of all models

### Why It Failed

1. **Trend derivative is too noisy** — responds to:
   - Sensor drift
   - Normal diurnal variation
   - Indoor activity (windows open, cooking)
   - Short-term weather fluctuations (not just rain)

2. **No absolute humidity anchor** — can't distinguish:
   - Rain approach (high humidity + narrowing spread)
   - Dry cold front (low humidity + narrowing spread)

3. **Over-conservative gating** — dry ceiling suppresses most alerts

### Lesson Learned

✅ **Dew-point proximity is the core signal**  
✅ **Trend is a useful reinforcement, not a standalone predictor**  
❌ **Trend-only models are too noisy and miss most events**

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

### 6. combined (Variant E)

**Status:** 🔧 Testing  
**Implementation:** `pressure_variants.py::model_combined`

**Full multi-signal model** using **all available environmental inputs**:
- Temperature trend (cooling = condensation signal)
- Absolute humidity trend (rising = more moisture available)
- All three pressure signals from `pressure_combined` (long window + lagged + absolute bonus)
- Core dew-point spread proximity and derivative

#### Algorithm

```python
# Core signals (same as other models)
proximity = clamp(100 - spread / proximity_divisor * 100, 0, 100)
trend_score = clamp(-spread_deriv * trend_gain, trend_floor, trend_ceiling)

# Temperature trend — cooling indicates condensation
if temp_trend < -0.5:  # significant cooling
    temp_score = min(-temp_trend * 8.0, 20.0)
elif temp_trend > 2.0:  # rapid warming (warm front)
    temp_score = min(temp_trend * 2.5, 8.0)

# Absolute humidity trend — rising humidity = more moisture
if abs_humidity_trend > 0:
    ah_score = min(abs_humidity_trend * 60.0, 25.0)

# Pressure signals (same as pressure_combined)
# - 12h long window for slow trends
# - 3h lagged short window
# - Absolute pressure bonus for cyclones

# Weighted blend with hysteresis
raw = proximity * 0.8 + trend_score * 0.5 + temp_score * 0.15 + ah_score * 0.18 + pressure_scores
result = hysteretic_decay(raw)
```

#### Why This Model?

The `combined` model is the **most comprehensive** approach, incorporating:

1. **Surface humidity signals** (spread proximity + derivative) — the baseline predictors
2. **Temperature dynamics** — distinguishes cooling (condensation) from warming (evaporation)
3. **Moisture availability** — absolute humidity trend shows water vapor influx
4. **Atmospheric pressure** — three complementary signals capture weather system approach

#### Graceful Degradation

Falls back when signals are unavailable:
- No temperature/humidity → behaves like `pressure_combined`
- No pressure → behaves like humidity-only model with temp/AH enhancement
- No environmental signals at all → pure spread-based model

#### Weights

| Signal | Weight | Rationale |
|--------|--------|-----------|
| Proximity | 0.8 | Core signal — absolute humidity |
| Spread derivative | 0.5 | Reinforcement — rate of change |
| Temperature trend | 0.15 | Secondary — condensation indicator |
| Abs humidity trend | 0.18 | Secondary — moisture availability |
| Pressure (long) | 0.25 | Tertiary — slow system approach |
| Pressure (short lagged) | 0.20 | Tertiary — recent drop |
| Pressure (absolute bonus) | 0.20 | Tertiary — cyclone presence |

#### Weight Interpretation

⚠️ **Important:** Weights in this model are **amplification coefficients**, not normalized probabilities.

- **Sum of weights:** 0.8 + 0.5 + 0.15 + 0.18 + 0.25 + 0.20 + 0.20 = **2.28** (not 1.0)
- Each signal is multiplied by its weight and summed
- The total can significantly exceed 100 before the final clamp to [0, 100]
- Higher weight = stronger influence on the final score

**Example calculation:**

```python
# Scenario: approaching storm with multiple positive signals
proximity = 80.0           # spread = 1.6°C (humid)
trend_score = 30.0         # narrowing at -1.5°C/h
temp_score = 12.0          # cooling at -1.5°C/h
ah_score = 15.0            # humidity rising
pressure_long = 25.0       # 12h pressure drop
pressure_short = 20.0      # 3h pressure drop
pressure_bonus = 10.0      # absolute pressure < 1000 hPa

# Raw calculation (before clamp)
raw = proximity * 0.8 + trend_score * 0.5 + temp_score * 0.15 + ah_score * 0.18 + 
      pressure_long * 0.25 + pressure_short * 0.20 + pressure_bonus * 0.20
    = 80 * 0.8 + 30 * 0.5 + 12 * 0.15 + 15 * 0.18 + 25 * 0.25 + 20 * 0.20 + 10 * 0.20
    = 64 + 15 + 1.8 + 2.7 + 6.25 + 4 + 2
    = 95.75

# Final result (after clamp to [0, 100])
result = clamp(95.75, 0, 100) = 96%
```

**Scenario with clamping:**

```python
# All signals strongly positive (unlikely but possible)
proximity = 100.0
trend_score = 30.0
temp_score = 20.0
ah_score = 25.0
pressure_scores_total = 55.0  # all three pressure signals maxed

# Raw calculation
raw = 100 * 0.8 + 30 * 0.5 + 20 * 0.15 + 25 * 0.18 + 55
    = 80 + 15 + 3 + 4.5 + 55
    = 157.5  # exceeds 100!

# Final result (clamped)
result = clamp(157.5, 0, 100) = 100%
```

**Why not normalized to 1.0?**
- The model uses **amplification** rather than **averaging**
- Multiple independent signals reinforce each other
- Clamping to [0, 100] at the end ensures a valid probability range
- This allows the model to distinguish between:
  - Weak rain signal (one indicator barely positive) → score ~40-60
  - Strong rain signal (multiple indicators aligned) → score ~80-100

This is intentional design, not an error. The weights control relative influence, not probability distribution.

---

## Future Models (Planned)

### 7. ensemble_vote (Future)

Majority-vote ensemble of top-3 models. Alerts only when 2+ models agree.

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

**Last Updated:** 2026-08-04  
**Maintainer:** Karasik (AI assistant for Kickoman/rain-analysis)
