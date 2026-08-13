# Prediction models — audit and improvement plan

## Context

With the measurement harness fixed (see `docs_site/CHANGELOG.md`, 2026-08-13), model
scores are finally trustworthy — and they are poor. The best model reaches F1 0.40
over 43 days. This document asks why, using the data now available: 43 days of local
sensor history and 5.6 years (49,200 hours) of Open-Meteo reanalysis for the same
coordinates.

The short answer is that **every model in the repository is built on the one input
that carries no signal**, while the strongest available inputs are either unused or
fed through a function that saturates. The deployed Telegram alert catches under 12%
of rain events under any definition tested.

## How the numbers below were produced

Two independent datasets, so that a finding is only reported when both agree:

- **Local (realistic, small):** `data/archive/ha_hourly.csv` joined with Open-Meteo
  and Meteostat, 2026-07-01 → 2026-08-13, 1036 hours. Pressure covers 770 of them
  (the DIY barometer's statistics begin 2026-07-12). Validated with expanding-window
  walk-forward — models are never scored on rows they trained on.
- **Long (trustworthy, large):** Open-Meteo archive 2021-01-01 → 2026-08-12, 49,200
  hours, 13,227 positives for the 3-hour target. Split temporally: train
  2021-01 → 2025-03, test 2025-03 → 2026-08 (12,294 held-out hours).

Ground truth throughout is precipitation ≥ 0.1 mm/h. Two targets are distinguished:
`y_now` (raining this hour) and `y_next3` (rain in any of the next three hours) —
the second is what a "bring the laundry in" alert actually needs.

> **Caveat, stated once and applying throughout.** The long dataset predicts
> Open-Meteo's precipitation from Open-Meteo's own reanalysis variables, so its
> absolute scores are optimistic — the two come from the same model. It is reliable
> for *ranking* features and for showing that a signal exists; it is not a promise of
> what the balcony sensor will achieve. Where an absolute number matters, the local
> dataset is quoted instead.

---

## Findings

### 1. The deployed alert misses roughly nine rain events in ten

The automation documented in `docs_site/MODELS.md` fires when
`spread < 4 °C AND spread_trend < −0.5 °C/h`, where the trend comes from Home
Assistant's 1-hour derivative helper. Evaluated over 49,196 hours, it fires on 7.2%
of them:

| target | precision | base rate | lift | recall |
|---|:---:|:---:|:---:|:---:|
| raining now | 0.298 | 0.187 | 1.59× | **0.114** |
| rain within 1h | 0.271 | 0.187 | 1.45× | **0.104** |
| rain within 3h | 0.339 | 0.271 | 1.25× | **0.090** |
| rain within 6h | 0.401 | 0.354 | 1.13× | **0.081** |

Precision is modestly better than chance — the rule is not entirely empty — but two
thirds of its alerts are still false, and **recall never exceeds 0.114 under any
definition**. It misses about nine rain events out of ten. The lift also decays as the
horizon lengthens (1.59× → 1.13×), which is the wrong direction for something sold as
an early warning: it is weakly detecting rain that has already begun rather than
anticipating it.

This is the most consequential finding here, because it is the part of the project
that actually runs in the house. The result is stable across trend definitions:
substituting a 2h, 3h or 6h slope moves precision between 0.203 and 0.339 and leaves
recall in the 0.081–0.118 band throughout.

### 2. The "dry-night false positive" premise is not just weak — it is inverted

`docs_site/BASELINE_MODEL.md` frames calm nights with a closing spread as the model's
central failure mode. Over 16,394 night hours (21:00–04:00 UTC), defining "spread
closes" as a drop of more than 2 °C over 6 hours ending below 4 °C:

| condition | P(rain in next 3h) |
|---|---|
| night, spread closes (n=4,077) | **20.3%** |
| night, otherwise (n=12,317) | **24.3%** |

A closing spread at night is *negatively* associated with rain. The baseline model
treats it as its primary positive signal.

Pressure separates the same hours cleanly:

| condition | P(rain in next 3h) |
|---|---|
| night, spread closes, pressure **below** median (n=1,945) | **33.9%** |
| night, spread closes, pressure **above** median (n=2,132) | **7.9%** |

A 4.3× difference. The intuition that "pressure fixes dry nights" was right; the
implementation never delivered it (finding 4).

### 3. The spread derivative — the core of every model — carries no signal

Single-feature AUC on the held-out long dataset:

| feature | AUC (y_now) | AUC (y_next3) |
|---|:---:|:---:|
| pressure (inverted) | **0.749** | **0.753** |
| cloud cover | 0.702 | 0.711 |
| spread_min over 6h (inverted) | 0.686 | 0.666 |
| relative humidity | 0.668 | 0.636 |
| pressure vs 72h mean (inverted) | 0.663 | 0.666 |
| dew-point spread (inverted) | 0.661 | 0.629 |
| absolute humidity | 0.603 | 0.604 |
| **spread derivative (3h)** | **0.492** | **0.535** |

0.492 is below chance. On the local dataset the recorded HA trend sensor scores
AUC 0.499 for `y_now` — indistinguishable from a coin flip. Both `proximity` and
`trend` in the current design are built from the bottom of this table.

### 4. The absolute-pressure bonus is calibrated for the wrong pressure

`scripts_utils/pressure_variants.py::_abs_pressure_bonus` awards +20 below 990 hPa,
+10 below 1000, +5 below 1005 — thresholds that describe **sea-level** pressure.
Minsk sits at ~220 m, so the station barometer reads ~25 hPa lower. Measured on
`sensor.filtered_pressure` (770 hours):

| | value |
|---|---|
| Local station pressure | min 978.0, median **989.6**, max 1001.1 |
| Meteostat sea-level pressure | min 995.7, median 1013.0, max 1027.4 |
| bonus = 20 | 51.8% of hours |
| bonus = 10 | 46.6% of hours |
| bonus = 5 | 1.6% of hours |
| bonus = 0 | **never** |
| mean ± sd | 15.10 ± 5.12 |

The function is saturated: it reports "deep cyclone" for half of all hours and never
returns zero. Applied to sea-level pressure it behaves as designed — non-zero on 9.0%
of hours, mean 0.57. In `pressure_absolute` (weight 0.3) and
`pressure_combined`/`combined` (weight 0.20) it acts as a near-constant offset of
roughly +3 to +4.5 points, shifting every score against a fixed 50% threshold rather
than discriminating anything. It does retain a trace of signal (mean 18.5 when
raining vs 14.5 when dry) precisely because pressure itself is informative — which is
the point of finding 3.

### 5. Every hand-tuned model is near chance; learned models are not

Local dataset, walk-forward, 455 held-out hours, target `y_next3`:

| model | AUC | best F1 |
|---|:---:|:---:|
| GBM (learned) | 0.757 | **0.477** |
| logistic regression (learned) | **0.764** | 0.438 |
| absolute pressure alone, inverted | 0.797 | 0.478 |
| persistence (it rained last hour) | 0.643 | 0.425 |
| Yandex `prec_prob` (external forecast) | 0.590 | 0.306 |
| `combined` (best heuristic) | 0.546 | 0.277 |
| `pressure_absolute` | 0.549 | 0.287 |
| `ha_live` (production) | **0.486** | 0.277 |
| `trend_dominant` | 0.500 | 0.297 |

The ten heuristics span AUC 0.486–0.549. **A single raw pressure reading beats all of
them.** The long dataset agrees and gives sharper numbers: a gradient-boosted model on
locally-available features reaches AUC 0.844 / F1 0.640, and adding cloud cover and
wind reaches AUC 0.877 / F1 0.677.

Two baselines nobody has been comparing against deserve attention. **Persistence**
scores F1 0.738 for nowcasting on the long dataset — no hand-built model comes close.
And **Yandex's own forecast is weak** (AUC 0.59–0.63), which is good news: it means
local sensing genuinely has room to add value rather than being strictly dominated by
a free API.

### 6. Feature importance says the model is looking in the wrong place

Permutation importance (drop in test AUC when a feature is shuffled), GBM on the long
dataset, target `y_next3`:

| rank | feature | ΔAUC | locally measurable? |
|:---:|---|:---:|---|
| 1 | cloud cover | +0.0614 | ✗ (API only) |
| 2 | **absolute pressure** | +0.0382 | ✓ |
| 3 | rained in the last hour | +0.0343 | ✗ (needs a rain sensor) |
| 4 | day of year | +0.0301 | ✓ (free) |
| 5 | hour of day | +0.0241 / +0.0123 | ✓ (free) |
| 6 | absolute humidity | +0.0122 | ✓ |
| 7 | wind speed | +0.0068 | ✗ |
| 8 | **spread derivative** | +0.0059 | ✓ |
| 13 | **dew-point spread** | +0.0026 | ✓ |

Seasonality and time of day — both free, both entirely absent from every model —
each matter more than the spread derivative. The two signals the project is built on
rank 8th and 13th.

### 7. Reachable operating points

GBM on the long dataset, target `y_next3`, held-out period, base rate 27.3%:

| target | precision | recall |
|---|:---:|:---:|
| precision ≥ 0.60 | 0.600 | 0.799 |
| precision ≥ 0.70 | 0.700 | 0.677 |
| precision ≥ 0.80 | 0.800 | 0.508 |
| recall ≥ 0.90 | 0.501 | 0.900 |

Against the deployed rule's precision 0.339 / recall 0.090 on the same target. Even
discounting the optimism of the long dataset, the gap is not marginal — every row
above more than triples the rule's recall.

### 8. Methodology problems in the modelling code

- **The target does not match the use case.** Models are scored on "is it raining this
  hour" (`rain_truth` at time *t*), but the product is a warning. `rainlib_temporal`
  bolts tolerance windows onto the metric afterwards; the cleaner fix is to define the
  label as "rain within the next N hours" and score it directly.
- **Grid search evaluates on its own training window.** `run_analysis.py::param_tuning`
  sweeps `proximity_divisor`, `hysteresis_decay` and `trend_gain` and reports the best
  F1 over the same window used for scoring. `MODELS.md` already notes the overfitting
  risk; there is no split to fix it.
- **Outputs are not probabilities.** Weights are amplification coefficients summing to
  1.4 (`ha_live`) or 2.28 (`combined`), clamped to [0, 100]. A fixed 50% threshold on
  such a score has no calibrated meaning, and the threshold interacts with the
  constant offset from finding 4.
- **No baselines are reported.** Persistence, climatology and the external forecast are
  never computed, so there has never been a floor to beat.
- **`derivative(window="1h")` silently returns all-NaN on the hourly grid.** The window
  mask is `x > t − win` (strict), so a 1-hour window on hourly data contains one
  sample, below `min_periods=2`. Models call `.fillna(0.0)` on the result, so this
  degrades to "no trend" without any error. No current default uses a 1h window
  (defaults are 3h/12h), so nothing is broken today — but it is a trap, and the same
  mechanism makes a "3h" window on hourly data span only 2 hours (3 samples).
- **`_setup_dataframe` forward-fills `spread` without a limit**
  (`pressure_variants.py:43`), so a dead sensor propagates indefinitely inside the
  model, contradicting the bounded fill `build_grid` applies upstream.
- **`derivative()` is O(n²)** — 0.52 s at 8,000 rows, ~20 s per column at 49,200. With a
  dozen derived columns a multi-year backtest spends minutes in this function. A
  trailing-difference or `rolling().apply` formulation is linear.

---

## Plan

### Stage 1 — Replace the deployed alert (highest value, lowest effort)

Finding 1 means the notification currently running misses nine rain events in ten, and
finding 2 gives the fix: gate on pressure rather than on the spread trend. A candidate
was fitted on 2021-01 → 2025-03 and measured on 12,258 held-out hours:

```
pressure_anomaly < −1 hPa   AND   relative_humidity > 75%
```

where `pressure_anomaly = pressure − rolling_median(pressure, 30 days)`. Held-out
period, target "rain within 3h", base rate 0.274:

| | precision | recall | fires | lift |
|---|:---:|:---:|:---:|:---:|
| deployed rule | 0.401 | **0.096** | 6.5% | 1.47× |
| candidate | **0.519** | **0.488** | 25.8% | 1.89× |

Recall improves 5.1×, and precision improves too — the candidate dominates on both
axes rather than trading one for the other. Note that a dew-point-spread term was
offered to the search and **rejected**: adding `spread < 4 °C` changed nothing,
consistent with findings 2 and 3.

Two things to settle before deploying it:

- **Notification fatigue.** Firing on 25.8% of hours is roughly six alerts a day. The
  rule needs edge-triggering (notify on the transition into the condition, not while
  it holds) and a minimum re-arm interval. This is an automation concern, not a model
  one, but it decides whether the alert is usable.
- The threshold pair is tuned on reanalysis, so re-check both numbers against the
  local barometer before committing. The 30-day rolling median is expressible in Home
  Assistant with a `statistics` sensor (`max_age: 30 days`), so no new infrastructure
  is required.

Deliverable: a replacement template + automation, with its measured precision/recall
on held-out data stated alongside the old rule's. Keep it a rule, not a model, so it
stays deployable as a template sensor.

### Stage 2 — Fix the target, the metrics and the baselines

These change what "better" means, so they come before new models.

1. Add `rain_within_hours: int = 3` to `AnalysisConfig` and build the label in
   `label_ground_truth()` as the forward maximum over that horizon. Keep `y_now`
   reported as a secondary column; do not remove it.
2. Add persistence, climatology and Yandex `prec_prob` as first-class entries in the
   `MODELS`-adjacent scoring path so every report shows the floor. Reuse
   `rl.confusion_at_threshold`; no new metric code required.
3. Report AUC and average precision next to F1. Both are threshold-free and would have
   exposed findings 3 and 5 years ago — F1 at a fixed threshold hides a model that
   cannot rank at all.
4. Split `param_tuning` into train/validation by time, or delete it. Reporting a
   grid-search optimum measured on its own training data is worse than reporting
   nothing.

### Stage 3 — Repair the physics-based models

Cheap, keeps interpretability, and worth doing even if a learned model wins later —
these are what can run as a Home Assistant template.

1. **Fix `_abs_pressure_bonus`.** Either take sea-level pressure as input (the local
   sensor plus a fixed elevation correction for ~220 m) or, better, replace the fixed
   thresholds with a station-relative anomaly: `pressure − rolling_median(30 days)`.
   The latter needs no elevation constant and adapts to season. Measured AUC of the
   72-hour version is 0.663–0.666 versus a saturated constant today.
2. **Promote pressure level from bonus to primary term** and demote the spread
   derivative from primary to secondary, matching the ordering in finding 6.
3. **Add hour-of-day and day-of-year.** They outrank the spread derivative, cost
   nothing, and need no sensor. In a template sensor this is a seasonal/diurnal
   multiplier.
4. Bound the forward fill in `_setup_dataframe`, and add a guard in `derivative()` that
   raises (or warns loudly) when the window is not strictly longer than the median
   sample spacing, instead of silently returning NaN.

### Stage 4 — Introduce a learned model

Only after stage 2, so it is measured against a meaningful target and real baselines.

1. **Logistic regression first**, not gradient boosting. It reached AUC 0.764 locally
   versus the GBM's 0.757 — statistically indistinguishable on this much data — and it
   yields inspectable coefficients and calibrated probabilities. A calibrated
   probability is what makes a threshold meaningful, which is exactly what
   `recommend_threshold` has been unable to assume.
2. Add a walk-forward evaluation harness (expanding window, train strictly on the
   past). This is ~30 lines and is the piece that makes any future model claim
   credible.
3. Only then try `HistGradientBoostingClassifier`. Training takes 1–3 s on 37k rows, so
   cost is not a concern; the concern is that it cannot run as a HA template and needs
   the backend to serve predictions — which is what Phase 3 of the roadmap already
   builds.
4. Add `scikit-learn` to `requirements.txt` when this stage starts, not before.
5. Persist the fitted model with its training window, feature list and measured
   held-out scores, so a deployed model is traceable to the data that produced it.

### Stage 5 — Close the data gaps

Ordered by measured value per unit of effort.

1. **Cloud cover** is the single most important feature (+0.061 AUC) and is available
   free from Open-Meteo's forecast endpoint. It is not measurable from the balcony, so
   using it changes the project from "local sensors only" to "local sensors plus an
   API". That is a real design decision and should be made deliberately rather than by
   drift — but the measurement says it is the largest single improvement available.
2. **A rain sensor** would deliver two things at once: the persistence feature (3rd by
   importance, and F1 0.738 alone for nowcasting) and, more importantly, a *local
   ground truth*. Open-Meteo and Meteostat agree only at κ = 0.495, so today a
   meaningful share of every measured error is the yardstick's. A tipping-bucket gauge
   or even a leaf-wetness sensor would resolve both.
3. **Wind** (+0.007) is marginal — worth adding only if a sensor appears for other
   reasons.
4. Keep archiving. Every finding here is limited by 43 days of local history; the
   archive added in the previous round is what lifts that ceiling over time.

---

## Verification

1. **Stage 1** — the new rule's precision and recall on the held-out period, next to the
   deployed rule's 0.401 / 0.096 on the same rows. Recall is the binding constraint:
   reject any replacement that does not at least triple it while holding precision at
   or above 0.40. Also count alerts per day — a rule that is right more often but fires
   six times a day has solved the wrong problem.
2. **Stage 2** — every report shows persistence and climatology. A model that cannot
   beat persistence is labelled as such rather than ranked above it.
3. **Stage 3** — `_abs_pressure_bonus` (or its replacement) returns a distribution with
   real spread on local pressure: it should be zero on most hours and saturate rarely.
   Today it is non-zero on 100% of hours and at 10 points or above on 98.4% of them.
4. **Stage 4** — walk-forward AUC on held-out local data above 0.75, versus 0.486–0.549
   for the current heuristics. Calibration checked with a reliability curve, not only
   F1.
5. **Regression guard** — a test asserting that no registered model scores below AUC
   0.55 on a fixed reference window, so a model that cannot rank never silently ships
   again.

## What was not tested

- Whether the local balcony sensor reproduces the long-dataset feature ranking in
  detail. Pressure and humidity do transfer (findings 3 and 5 agree across both
  datasets); cloud cover and wind could not be checked locally at all.
- Radar or satellite nowcasting, which is the standard approach for 0–3 hour horizons
  and would likely beat everything here — at the cost of no longer being a
  sensor-driven project.
- Precipitation *amount*, and any threshold other than 0.1 mm/h.
- Whether κ = 0.495 between the ground-truth sources places a ceiling on measurable
  performance. It probably does, and a local rain gauge is the way to find out.

---

_Written 2026-08-13. Experiments are reproducible from `data/archive/ha_hourly.csv`
plus the Open-Meteo archive endpoint; see "How the numbers below were produced"._
