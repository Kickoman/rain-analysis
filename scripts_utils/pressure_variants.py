"""
pressure_variants.py — Experimental pressure-aware model variants
==================================================================

Four different approaches to using atmospheric pressure for rain prediction,
testing different hypotheses about how pressure relates to precipitation.

Created for issue #40: exploring why pressure_aware model shows identical
metrics to the baseline model.

Variants:
- A (absolute): Use both pressure trend AND absolute pressure level
- B (long_window): Use longer time windows (6h/12h) to catch slow trends
- C (lagged): Use lagged pressure (6h ago) as predictor
- D (combined): Combination of all above approaches

Refactored (issue #51): Common interpolation loop extracted into
_pressure_variant_base() to eliminate ~70% code duplication.
"""

from __future__ import annotations
import math
import numpy as np
import pandas as pd
from analysis.rainlib import ModelContext, ModelParams, derivative, _clamp


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _is_invalid(val) -> bool:
    """Return True if *val* is None or a float NaN (missing sensor data)."""
    return val is None or (isinstance(val, float) and math.isnan(val))


# A spread reading older than this no longer describes current conditions. The
# fill used to be unbounded, so a dead sensor propagated its last value through
# the rest of the run — inside the model, and therefore invisible to the
# coverage figures, which are computed on the grid upstream where the fill *is*
# bounded.
SPREAD_FFILL_LIMIT = pd.Timedelta(hours=3)


def _setup_dataframe(ctx: ModelContext) -> pd.DataFrame:
    """Create the common aligned DataFrame with spread and derivative."""
    df = pd.DataFrame({
        "spread": ctx.spread,
        "deriv": ctx.spread_deriv,
    }).sort_index()

    spread = df["spread"].dropna()
    if spread.empty:
        df["deriv"] = df["deriv"].fillna(0.0)
        return df

    df["spread"] = spread.reindex(df.index, method="ffill",
                                  tolerance=SPREAD_FFILL_LIMIT)
    df["deriv"] = df["deriv"].fillna(0.0)
    return df


def _align_pressure(ctx: ModelContext, df: pd.DataFrame) -> tuple[pd.Series | None, bool]:
    """Align pressure data to the model DataFrame.

    Returns (aligned_pressure, use_pressure).
    """
    use_pressure = ctx.pressure is not None and not ctx.pressure.dropna().empty
    if not use_pressure:
        return None, False
    return ctx.pressure.reindex(df.index).ffill(), True


# ---------------------------------------------------------------------------
# Base variant loop — handles ALL shared logic
# ---------------------------------------------------------------------------

def _pressure_variant_base(
    ctx: ModelContext,
    p: ModelParams,
    prepare_fn,
    score_fn,
) -> pd.Series:
    """Generic hysteresis loop shared by all pressure variant models.

    Parameters
    ----------
    ctx : ModelContext
    p : ModelParams
    prepare_fn : callable(df, p_aligned, p)
        Called once to add pressure-derived columns to *df*.
    score_fn : callable(i, df, use_pressure, p) -> list[tuple[float, float]]
        Called per timestep. Returns a list of ``(score, weight)`` pairs.
        The base loop multiplies each pair and adds the result to the blend.

    Returns
    -------
    pd.Series  – rounded rain probability 0–100.
    """
    df = _setup_dataframe(ctx)
    p_aligned, use_pressure = _align_pressure(ctx, df)

    # Always call prepare_fn (model_combined needs it for temp/humidity even without pressure)
    prepare_fn(df, p_aligned, p)

    out = np.full(len(df), np.nan)
    prev = None
    spread_v = df["spread"].values
    deriv_v = df["deriv"].values

    for i in range(len(df)):
        s = spread_v[i]
        d = deriv_v[i]

        # ── NaN guard for required inputs ──────────────────────────
        if _is_invalid(s):
            out[i] = prev if prev is not None else np.nan
            continue
        if _is_invalid(d):
            d = 0.0

        # ── Shared proximity + trend ───────────────────────────────
        proximity = max(min(100.0 - (s / p.proximity_divisor * 100.0), 100), 0)
        trend_score = min(max(-d * p.trend_gain, p.trend_floor), p.trend_ceiling)

        # ── Variant-specific pressure scores ───────────────────────
        p_scores = score_fn(i, df, use_pressure, p)

        # ── Weighted blend ─────────────────────────────────────────
        raw = proximity * p.proximity_weight + trend_score * p.trend_weight
        for score, weight in p_scores:
            raw += score * weight

        # ── Dry-spread ceiling ─────────────────────────────────────
        ceiling = 100.0 if s < p.dry_spread_cutoff else p.dry_ceiling
        raw = max(min(raw, ceiling), 0)

        # ── Hysteresis ─────────────────────────────────────────────
        if prev is None:
            total = raw
        elif raw > prev:
            total = raw
        else:
            total = prev - (prev - raw) * p.hysteresis_decay
        out[i] = total
        prev = total

    return pd.Series(out, index=df.index).round(0)



# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _pressure_score(pd_val, threshold, gain, ceiling, floor):
    """Standard pressure derivative score: zero below threshold, clamped above."""
    if abs(pd_val) < abs(threshold):
        return 0.0
    return max(min(-pd_val * gain, ceiling), floor)


# Reference thresholds are expressed as a *departure from the station's own
# recent normal*, in hPa. Fixed absolute cut-offs cannot work here: they were
# written for sea-level pressure (990/1000/1005 hPa), but the barometer sits at
# ~220 m, where station pressure has a median of 989.6 and never exceeds 1001.
# Against those cut-offs the bonus returned 20 for 51.8% of hours, 10 for 46.6%,
# and zero never — a constant offset of ~15 points dressed up as a cyclone
# detector. An anomaly needs no elevation constant and tracks the season.
PRESSURE_ANOMALY_BONUS = (
    (-8.0, 20.0),   # deep low relative to the local normal
    (-4.0, 10.0),
    (-1.5, 5.0),
)

# Window for "recent normal". Long enough to span several synoptic systems so a
# multi-day low still reads as low, short enough to follow the seasonal cycle.
PRESSURE_BASELINE_WINDOW = "30D"


def _abs_pressure_bonus(anomaly):
    """Bonus for pressure below the station's own recent normal (cyclone indicator).

    Takes an *anomaly* in hPa (current minus rolling median), not a raw reading.
    """
    if anomaly is None or (isinstance(anomaly, float) and math.isnan(anomaly)):
        return 0.0
    for threshold, bonus in PRESSURE_ANOMALY_BONUS:
        if anomaly < threshold:
            return bonus
    return 0.0


def pressure_anomaly(pressure: pd.Series,
                     window: str = PRESSURE_BASELINE_WINDOW) -> pd.Series:
    """Pressure minus its own trailing median — a station-relative "how low is low".

    Trailing only, so no future data leaks into a past row. Rows before the
    window has enough history yield NaN, which the scorers read as "no signal"
    rather than as a reading of zero.
    """
    baseline = pressure.rolling(window, min_periods=24).median()
    return pressure - baseline


# ---------------------------------------------------------------------------
# Variant A: Absolute pressure
# ---------------------------------------------------------------------------

def model_pressure_absolute(ctx: ModelContext,
                            p: ModelParams | None = None) -> pd.Series:
    """Variant A: Pressure trend + absolute pressure level.

    Hypothesis: Low absolute pressure (<1000 hPa) is itself a rain indicator,
    even if pressure is currently rising. This catches situations where:
    - We're in a low-pressure system (cyclone)
    - Pressure is recovering but rain continues
    """
    if p is None:
        p = ModelParams()

    def prepare(df, p_aligned, p):
        if p_aligned is None:
            return
        df["pres_deriv"] = derivative(p_aligned, window=p.pressure_window).fillna(0.0)
        df["pres_anom"] = pressure_anomaly(p_aligned)

    def get_scores(i, df, use_pressure, p):
        if not use_pressure:
            return []
        pd_val = df["pres_deriv"].values[i]
        anomaly = df["pres_anom"].values[i]

        if _is_invalid(pd_val):
            pd_val = 0.0

        ps = _pressure_score(pd_val, p.pressure_drop_threshold,
                            p.pressure_gain, p.pressure_ceiling, p.pressure_floor)
        bonus = _abs_pressure_bonus(anomaly)
        return [(ps, p.pressure_weight), (bonus, 0.3)]

    return _pressure_variant_base(ctx, p, prepare, get_scores)


# ---------------------------------------------------------------------------
# Variant B: Long window
# ---------------------------------------------------------------------------

def model_pressure_long_window(ctx: ModelContext,
                               p: ModelParams | None = None) -> pd.Series:
    """Variant B: Longer pressure derivative windows (12h).

    Hypothesis: 3h window is too short to catch the slow pressure changes
    that precede weather systems. Use 12h window to see the bigger picture.
    """
    if p is None:
        p = ModelParams()

    def prepare(df, p_aligned, p):
        if p_aligned is None:
            return
        df["pres_deriv"] = derivative(p_aligned, window="12h").fillna(0.0)

    def get_scores(i, df, use_pressure, p):
        if not use_pressure:
            return []
        pd_val = df["pres_deriv"].values[i]
        if _is_invalid(pd_val):
            pd_val = 0.0

        # More relaxed threshold for 12h window (slower changes)
        ps = _pressure_score(pd_val, 0.1,
                            p.pressure_gain, p.pressure_ceiling, p.pressure_floor)
        return [(ps, p.pressure_weight)]

    return _pressure_variant_base(ctx, p, prepare, get_scores)


# ---------------------------------------------------------------------------
# Variant C: Lagged pressure
# ---------------------------------------------------------------------------

def model_pressure_lagged(ctx: ModelContext,
                          p: ModelParams | None = None) -> pd.Series:
    """Variant C: Lagged pressure as predictor (6h).

    Hypothesis: Pressure changes 6 hours ago predict rain now. This accounts
    for the time it takes for a weather system to arrive after pressure drop.
    """
    if p is None:
        p = ModelParams()

    def prepare(df, p_aligned, p):
        if p_aligned is None:
            return
        p_lagged = p_aligned.shift(freq="6h")
        df["pres_deriv"] = derivative(p_lagged, window=p.pressure_window).fillna(0.0)

    def get_scores(i, df, use_pressure, p):
        if not use_pressure:
            return []
        pd_val = df["pres_deriv"].values[i]
        if _is_invalid(pd_val):
            pd_val = 0.0

        ps = _pressure_score(pd_val, p.pressure_drop_threshold,
                            p.pressure_gain, p.pressure_ceiling, p.pressure_floor)
        return [(ps, p.pressure_weight)]

    return _pressure_variant_base(ctx, p, prepare, get_scores)


# ---------------------------------------------------------------------------
# Variant D: Combined
# ---------------------------------------------------------------------------

def model_pressure_combined(ctx: ModelContext,
                            p: ModelParams | None = None) -> pd.Series:
    """Variant D: Combined approach using all techniques.

    Combines:
    - Long window (12h) for slow trends
    - Absolute pressure bonus for low pressure systems
    - Lagged pressure (3h lag, compromise)

    This is the "kitchen sink" approach to see if multiple signals
    together work better than any single one.
    """
    if p is None:
        p = ModelParams()

    def prepare(df, p_aligned, p):
        if p_aligned is None:
            return
        # Long-term trend (12h window)
        df["pres_long"] = derivative(p_aligned, window="12h").fillna(0.0)
        # Short-term trend (3h window, lagged by 3h)
        p_lagged = p_aligned.shift(freq="3h")
        df["pres_short"] = derivative(p_lagged, window="3h").fillna(0.0)
        # How low the station is sitting relative to its own recent normal
        df["pres_anom"] = pressure_anomaly(p_aligned)

    def get_scores(i, df, use_pressure, p):
        if not use_pressure:
            return []
        p_long = df["pres_long"].values[i]
        p_short = df["pres_short"].values[i]
        anomaly = df["pres_anom"].values[i]

        if _is_invalid(p_long):
            p_long = 0.0
        if _is_invalid(p_short):
            p_short = 0.0

        # Long-term pressure trend (12h window)
        # Use relaxed threshold for slower changes
        long_score = _pressure_score(p_long, 0.1,
                                    p.pressure_gain, p.pressure_ceiling, p.pressure_floor)
        # Short-term lagged pressure (3h window)
        short_score = _pressure_score(p_short, 0.3,
                                     p.pressure_gain, p.pressure_ceiling, p.pressure_floor)
        # Pressure-anomaly bonus
        abs_bonus = _abs_pressure_bonus(anomaly)

        return [(long_score, 0.25), (short_score, 0.20), (abs_bonus, 0.20)]

    return _pressure_variant_base(ctx, p, prepare, get_scores)



# ---------------------------------------------------------------------------
# Variant E: True Combined (temperature + humidity + pressure)
# ---------------------------------------------------------------------------

def model_combined(ctx: ModelContext,
                   p: ModelParams | None = None) -> pd.Series:
    """Fully combined model using ALL available signals.

    Incorporates temperature trend, absolute humidity trend, and all three
    pressure signals (long window, lagged, absolute bonus) alongside the
    core spread proximity and spread derivative.

    Temperature: cooling trend = condensation → rain signal.
    Absolute humidity: rising → more moisture → stronger rain precursor.
    Pressure: long window + lagged + absolute bonus (same as pressure_combined).

    Falls back gracefully when temp/abs_humidity or pressure are unavailable.

    Refactored in issue #262 to use _pressure_variant_base() instead of
    duplicating the hysteresis loop.
    """
    if p is None:
        p = ModelParams()

    def prepare(df, p_aligned, p):
        # Temperature and absolute humidity
        use_env = (ctx.temp is not None and not ctx.temp.dropna().empty and
                   ctx.abs_humidity is not None and not ctx.abs_humidity.dropna().empty)
        if use_env:
            temp_aligned = ctx.temp.reindex(df.index).ffill()
            ah_aligned = ctx.abs_humidity.reindex(df.index).ffill()
            df['temp_trend'] = derivative(temp_aligned, window='3h').fillna(0.0)
            df['abs_hum_trend'] = derivative(ah_aligned, window='3h').fillna(0.0)
        else:
            df['temp_trend'] = 0.0
            df['abs_hum_trend'] = 0.0

        # Pressure signals (if available, already handled by base)
        if p_aligned is not None:
            df['pres_long'] = derivative(p_aligned, window='12h').fillna(0.0)
            p_lagged = p_aligned.shift(freq='3h')
            df['pres_short'] = derivative(p_lagged, window='3h').fillna(0.0)
            df['pres_anom'] = pressure_anomaly(p_aligned)

    def get_scores(i, df, use_pressure, p):
        scores = []

        # ── Temperature trend ────────────────────────────────────────
        # Cooling = condensation → rain signal
        # Rapid warming (warm front) = mild precursor
        tt = df['temp_trend'].values[i]
        if not _is_invalid(tt):
            if tt < -0.5:   # significant cooling
                temp_score = min(-tt * 8.0, 20.0)
                scores.append((temp_score, 0.15))
            elif tt > 2.0:  # rapid warming
                temp_score = min(tt * 2.5, 8.0)
                scores.append((temp_score, 0.15))

        # ── Absolute humidity trend ──────────────────────────────────
        # Rising abs humidity = more available moisture
        ah = df['abs_hum_trend'].values[i]
        if not _is_invalid(ah) and ah > 0:
            ah_score = min(ah * 60.0, 25.0)
            scores.append((ah_score, 0.18))

        # ── Pressure scores (same as pressure_combined) ──────────────
        if use_pressure:
            p_long = df['pres_long'].values[i]
            p_short = df['pres_short'].values[i]
            anomaly = df['pres_anom'].values[i]

            if not _is_invalid(p_long):
                long_score = _pressure_score(p_long, 0.1,
                                            p.pressure_gain, p.pressure_ceiling, p.pressure_floor)
                scores.append((long_score, 0.25))
            if not _is_invalid(p_short):
                short_score = _pressure_score(p_short, 0.3,
                                             p.pressure_gain, p.pressure_ceiling, p.pressure_floor)
                scores.append((short_score, 0.20))
            if not _is_invalid(anomaly):
                scores.append((_abs_pressure_bonus(anomaly), 0.20))

        return scores

    return _pressure_variant_base(ctx, p, prepare, get_scores)



# ---------------------------------------------------------------------------
# Variant F: signals ordered by measured value
# ---------------------------------------------------------------------------

# Anomaly (hPa below the station's own normal) that maps to a full-strength
# pressure signal. Chosen from the observed spread of the anomaly rather than
# tuned against the label.
PRESSURE_FULL_SCALE = -10.0

# Term weights, set from measured single-feature ROC AUC over 49,200 hours
# rather than by hand: pressure 0.75, dew-point spread 0.66, spread derivative
# 0.49. The derivative is at chance, so it contributes only a nudge — the
# opposite of every other model here, where it is the primary signal.
W_PRESSURE = 0.60
W_PROXIMITY = 0.40
W_TREND = 0.10

# A monotone rescaling of the blend, not fitted to the label. It exists so the
# documented 50% decision threshold sits inside the model's range: without it
# the weights above put the 90th percentile at 36, so the model crossed 50 on
# 4.2% of hours and looked useless at a fixed threshold while ranking best of
# the physics models on AUC.
#
# Being monotone it leaves the ranking itself alone, save for one second-order
# effect: outputs are rounded to whole numbers, and a wider range rounds fewer
# distinct scores onto the same value, which slightly reduces ties.
#
# That every model needs a different threshold — 45 for `combined`, 20 for
# `tuned`, 5 for `ha_live` — is the deeper problem here, and is what calibrated
# probabilities from the learned model are meant to end.
SCORE_SCALE = 2.0

# Rain within the next 3 hours peaks at 11h UTC (1.32x the base rate) and
# bottoms out around 20h UTC (0.74x) — afternoon convection. The seasonal cycle
# is real but not sinusoidal (peaks in both January and July over 5.6 years), so
# a smooth physics term cannot use it; that is left to the learned model.
DIURNAL_PEAK_HOUR_UTC = 11
DIURNAL_AMPLITUDE = 0.15


def _diurnal_factor(index) -> np.ndarray:
    """Multiplier for the time of day, peaking mid-afternoon local time.

    Falls back to a flat 1.0 when the index carries no clock — synthetic
    fixtures and unit tests often use a plain RangeIndex, and a model in the
    registry has to survive being called with one.
    """
    if not isinstance(index, pd.DatetimeIndex):
        return np.ones(len(index))
    phase = 2 * np.pi * (index.hour - DIURNAL_PEAK_HOUR_UTC) / 24.0
    return 1.0 + DIURNAL_AMPLITUDE * np.cos(phase)


def model_pressure_primary(ctx: ModelContext,
                           p: ModelParams | None = None) -> pd.Series:
    """Pressure-led model: the signals weighted by how well they actually predict.

    Every other model here is built on the dew-point-spread derivative, which
    measures at ROC AUC 0.49 — chance — while absolute pressure reaches 0.75 and
    is used only through a saturated step function. This inverts that ordering:
    a station-relative pressure anomaly is the primary term, humidity proximity
    is secondary, the derivative is a nudge, and the whole thing is scaled by
    time of day.

    Stateless, unlike the other stateful variants: with pressure leading there is
    no fast-moving derivative to smooth, so hysteresis would only add lag. That
    also keeps it expressible as a Home Assistant template.
    """
    if p is None:
        p = ModelParams()

    df = _setup_dataframe(ctx)
    p_aligned, use_pressure = _align_pressure(ctx, df)

    proximity = np.clip(100.0 - (df["spread"] / p.proximity_divisor * 100.0), 0, 100)
    trend = np.clip(-df["deriv"] * p.trend_gain, p.trend_floor, p.trend_ceiling)

    if use_pressure:
        anomaly = pressure_anomaly(p_aligned)
        # Linear, not stepped: the step version threw away most of the signal by
        # returning the same 20 points for anomalies of -8 and -25 hPa.
        pressure_score = np.clip(anomaly / PRESSURE_FULL_SCALE * 100.0, 0, 100).fillna(0.0)
    else:
        pressure_score = pd.Series(0.0, index=df.index)

    raw = (pressure_score * W_PRESSURE
           + proximity * W_PROXIMITY
           + trend * W_TREND) * SCORE_SCALE
    raw = raw * _diurnal_factor(df.index)

    # Dry air still vetoes: no pressure anomaly makes rain out of desert air.
    ceiling = np.where(df["spread"] < p.dry_spread_cutoff, 100.0, p.dry_ceiling)
    return pd.Series(np.clip(raw, 0, ceiling), index=df.index).round(0)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PRESSURE_VARIANTS = {
    "pressure_absolute": model_pressure_absolute,
    "pressure_long_window": model_pressure_long_window,
    "pressure_lagged": model_pressure_lagged,
    "pressure_combined": model_pressure_combined,
    "combined": model_combined,
    "pressure_primary": model_pressure_primary,
}


# ---------------------------------------------------------------------------
# Onset gate: the model for the project's actual question
# ---------------------------------------------------------------------------

# Logistic coefficients fitted on 2021-01→2025-03 Open-Meteo reanalysis for
# Minsk (36,846 dry hours) against the front-3h target: from a known-dry hour,
# does rain BEGIN within 3 hours? Frozen here — the model never refits — so its
# local scores are out-of-sample by construction. Validation, all held out:
#   reanalysis 2025-03→2026-08: front-3h ROC AUC 0.706
#   local sensors 2026-07→08:   front-3h ROC AUC 0.739
# against 0.54–0.61 for every other model in this registry on the same target.
#
# The feature set is the point. No dew-point-spread term and no spread
# derivative: at a dry hour a narrowing spread argues *against* an onset
# (front-3h AUC 0.42 — anti-correlated), which is why spread-led models
# cannot see fronts coming. What does predict an onset is how low pressure
# sits against its own month (anom), how far it has fallen off its 24-hour
# ridge (peak24), how moist the air already is (rh), and — counterintuitively
# but consistently — *rising* temperature over the last 3 h (temp_d3): the
# convective signature of a warming surface feeding an afternoon shower.
ONSET_GATE_COEF = {
    "intercept": -1.8297,
    "anom": -0.0648,      # hPa below trailing 30-day median
    "peak24": +0.0248,    # hPa fallen from the trailing 24-hour max
    "rh": +0.0209,        # %
    "temp_d3": +0.7231,   # °C per hour over the trailing 3 h
}


def _relative_humidity_from_spread(temp: pd.Series, spread: pd.Series) -> pd.Series:
    """Invert the Magnus dew-point formula: RH from temperature and spread."""
    from analysis.rainlib import MAGNUS_A, MAGNUS_B
    dew = temp - spread
    rh = 100.0 * np.exp(MAGNUS_A * dew / (MAGNUS_B + dew)
                        - MAGNUS_A * temp / (MAGNUS_B + temp))
    return rh.clip(1.0, 100.0)


def model_onset_gate(ctx: ModelContext,
                     p: ModelParams | None = None) -> pd.Series:
    """Rain-*onset* detector: P(rain begins within 3 h | dry now), as 0–100.

    Every other model here answers "does it look rainy" — a question dominated
    by hours when rain has already started. This one is tuned for the single
    transition the Telegram alert exists for, using the frozen logistic above.
    Output is 100·sigmoid(z), so 50 means "as likely as not, for an onset
    window" rather than an arbitrary point on an uncalibrated scale.

    Stateless and template-expressible: two rolling pressure statistics, RH,
    and a 3-hour temperature difference.

    Degrades honestly: without pressure the two pressure terms drop out of z
    (score from moisture and warming alone); without temperature history the
    temp_d3 term is 0. It never invents a reading.
    """
    df = _setup_dataframe(ctx)
    p_aligned, use_pressure = _align_pressure(ctx, df)
    c = ONSET_GATE_COEF

    z = pd.Series(c["intercept"], index=df.index)

    if use_pressure:
        anom = pressure_anomaly(p_aligned)
        peak24 = p_aligned.rolling("24h", min_periods=6).max() - p_aligned
        z = z + (c["anom"] * anom).fillna(0.0) + (c["peak24"] * peak24).fillna(0.0)

    if ctx.temp is not None and not ctx.temp.dropna().empty:
        temp = ctx.temp.reindex(df.index).ffill()
        rh = _relative_humidity_from_spread(temp, df["spread"])
        z = z + c["rh"] * rh.fillna(rh.median())
        temp_3h_ago = temp.shift(freq="3h").reindex(df.index)
        temp_d3 = ((temp - temp_3h_ago) / 3.0).fillna(0.0)
        z = z + c["temp_d3"] * temp_d3
    else:
        # No temperature: hold the moisture term at its neutral fitted point
        # (rh 70%) instead of silently dropping a third of the model.
        z = z + c["rh"] * 70.0

    score = 100.0 / (1.0 + np.exp(-z))
    return pd.Series(score, index=df.index).round(0)


# Defined below the registry dict, so registered here.
PRESSURE_VARIANTS["onset_gate"] = model_onset_gate
