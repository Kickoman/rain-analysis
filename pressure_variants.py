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
from rainlib import ModelContext, ModelParams, derivative, _clamp


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _is_invalid(val) -> bool:
    """Return True if *val* is None or a float NaN (missing sensor data)."""
    return val is None or (isinstance(val, float) and math.isnan(val))


def _setup_dataframe(ctx: ModelContext) -> pd.DataFrame:
    """Create the common aligned DataFrame with spread and derivative."""
    df = pd.DataFrame({
        "spread": ctx.spread,
        "deriv": ctx.spread_deriv,
    }).sort_index()
    df["spread"] = df["spread"].ffill()
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

    if use_pressure:
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


def _abs_pressure_bonus(p_abs):
    """Bonus score for low absolute pressure (cyclone indicator)."""
    if p_abs < 990:
        return 20.0
    elif p_abs < 1000:
        return 10.0
    elif p_abs < 1005:
        return 5.0
    return 0.0


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
        df["pres_deriv"] = derivative(p_aligned, window=p.pressure_window).fillna(0.0)
        df["pres_abs"] = p_aligned

    def get_scores(i, df, use_pressure, p):
        if not use_pressure:
            return []
        pd_val = df["pres_deriv"].values[i]
        p_abs = df["pres_abs"].values[i]

        if _is_invalid(pd_val):
            pd_val = 0.0
        if _is_invalid(p_abs):
            p_abs = 1013.25

        ps = _pressure_score(pd_val, p.pressure_drop_threshold,
                            p.pressure_gain, p.pressure_ceiling, p.pressure_floor)
        bonus = _abs_pressure_bonus(p_abs)
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
        # Long-term trend (12h window)
        df["pres_long"] = derivative(p_aligned, window="12h").fillna(0.0)
        # Short-term trend (3h window, lagged by 3h)
        p_lagged = p_aligned.shift(freq="3h")
        df["pres_short"] = derivative(p_lagged, window="3h").fillna(0.0)
        # Absolute pressure
        df["pres_abs"] = p_aligned

    def get_scores(i, df, use_pressure, p):
        if not use_pressure:
            return []
        p_long = df["pres_long"].values[i]
        p_short = df["pres_short"].values[i]
        p_abs = df["pres_abs"].values[i]

        if _is_invalid(p_long):
            p_long = 0.0
        if _is_invalid(p_short):
            p_short = 0.0
        if _is_invalid(p_abs):
            p_abs = 1013.25

        # Long-term pressure trend (12h window)
        long_score = _pressure_score(p_long, 0.1, 15.0, 25.0, -15.0)
        # Short-term lagged pressure (3h window)
        short_score = _pressure_score(p_short, 0.3, 20.0, 20.0, -10.0)
        # Absolute pressure bonus
        abs_bonus = _abs_pressure_bonus(p_abs)

        return [(long_score, 0.25), (short_score, 0.20), (abs_bonus, 0.20)]

    return _pressure_variant_base(ctx, p, prepare, get_scores)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PRESSURE_VARIANTS = {
    "pressure_absolute": model_pressure_absolute,
    "pressure_long_window": model_pressure_long_window,
    "pressure_lagged": model_pressure_lagged,
    "pressure_combined": model_pressure_combined,
}
