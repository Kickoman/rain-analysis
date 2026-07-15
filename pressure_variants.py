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
"""

from __future__ import annotations
import math
import numpy as np
import pandas as pd
from rainlib import ModelContext, ModelParams, derivative


def model_pressure_absolute(ctx: ModelContext,
                           p: ModelParams | None = None) -> pd.Series:
    """Variant A: Pressure trend + absolute pressure level.
    
    Hypothesis: Low absolute pressure (<1000 hPa) is itself a rain indicator,
    even if pressure is currently rising. This catches situations where:
    - We're in a low-pressure system (cyclone)
    - Pressure is recovering but rain continues
    
    Implementation:
    - Use pressure derivative as before (falling = rain likely)
    - Add bonus when absolute pressure < 1000 hPa
    - Larger bonus for very low pressure (< 990 hPa)
    """
    if p is None:
        p = ModelParams()

    df = pd.DataFrame({
        "spread": ctx.spread,
        "deriv": ctx.spread_deriv,
    }).sort_index()
    df["spread"] = df["spread"].ffill()
    df["deriv"] = df["deriv"].fillna(0.0)

    use_pressure = ctx.pressure is not None and not ctx.pressure.dropna().empty
    if use_pressure:
        p_aligned = ctx.pressure.reindex(df.index).ffill()
        df["pres_deriv"] = derivative(p_aligned, window=p.pressure_window)
        df["pres_deriv"] = df["pres_deriv"].fillna(0.0)
        df["pres_abs"] = p_aligned

    out = np.full(len(df), np.nan)
    prev = None
    spread_v = df["spread"].values
    deriv_v = df["deriv"].values
    pres_v = df["pres_deriv"].values if use_pressure else np.zeros(len(df))
    pres_abs_v = df["pres_abs"].values if use_pressure else np.full(len(df), 1013.25)

    for i in range(len(df)):
        s = spread_v[i]
        d = deriv_v[i]
        pd_val = pres_v[i]
        p_abs = pres_abs_v[i]

        if s is None or (isinstance(s, float) and math.isnan(s)):
            out[i] = prev if prev is not None else np.nan
            continue
        if d is None or (isinstance(d, float) and math.isnan(d)):
            d = 0.0
        if pd_val is None or (isinstance(pd_val, float) and math.isnan(pd_val)):
            pd_val = 0.0
        if p_abs is None or (isinstance(p_abs, float) and math.isnan(p_abs)):
            p_abs = 1013.25

        proximity = min(max(100.0 - (s / p.proximity_divisor * 100.0), 0), 100)
        trend_score = min(max(-d * p.trend_gain, p.trend_floor), p.trend_ceiling)

        # Pressure derivative component
        if abs(pd_val) < abs(p.pressure_drop_threshold):
            pressure_score = 0.0
        else:
            pressure_score = min(max(-pd_val * p.pressure_gain,
                                     p.pressure_floor),
                                 p.pressure_ceiling)

        # Absolute pressure bonus
        abs_bonus = 0.0
        if use_pressure:
            if p_abs < 990:
                abs_bonus = 20.0  # Very low pressure
            elif p_abs < 1000:
                abs_bonus = 10.0  # Low pressure
            elif p_abs < 1005:
                abs_bonus = 5.0   # Slightly low

        if use_pressure:
            raw = (proximity * p.proximity_weight +
                   trend_score * p.trend_weight +
                   pressure_score * p.pressure_weight +
                   abs_bonus * 0.3)  # New term
        else:
            raw = (proximity * p.proximity_weight +
                   trend_score * p.trend_weight)

        ceiling = 100.0 if s < p.dry_spread_cutoff else p.dry_ceiling
        raw = min(max(raw, 0), ceiling)

        if prev is None:
            total = raw
        elif raw > prev:
            total = raw
        else:
            total = prev - (prev - raw) * p.hysteresis_decay
        out[i] = total
        prev = total

    return pd.Series(out, index=df.index).round(0)


def model_pressure_long_window(ctx: ModelContext,
                               p: ModelParams | None = None) -> pd.Series:
    """Variant B: Longer pressure derivative windows (6h, 12h).
    
    Hypothesis: 3h window is too short to catch the slow pressure changes
    that precede weather systems. Use 12h window to see the bigger picture.
    
    Implementation:
    - Use 12h window for pressure derivative instead of 3h
    - This should filter out short-term fluctuations
    - Catch the slow approach of a cyclone
    """
    if p is None:
        p = ModelParams()

    df = pd.DataFrame({
        "spread": ctx.spread,
        "deriv": ctx.spread_deriv,
    }).sort_index()
    df["spread"] = df["spread"].ffill()
    df["deriv"] = df["deriv"].fillna(0.0)

    use_pressure = ctx.pressure is not None and not ctx.pressure.dropna().empty
    if use_pressure:
        p_aligned = ctx.pressure.reindex(df.index).ffill()
        # Key change: 12h window instead of 3h
        df["pres_deriv"] = derivative(p_aligned, window="12h")
        df["pres_deriv"] = df["pres_deriv"].fillna(0.0)

    out = np.full(len(df), np.nan)
    prev = None
    spread_v = df["spread"].values
    deriv_v = df["deriv"].values
    pres_v = df["pres_deriv"].values if use_pressure else np.zeros(len(df))

    for i in range(len(df)):
        s = spread_v[i]
        d = deriv_v[i]
        pd_val = pres_v[i]

        if s is None or (isinstance(s, float) and math.isnan(s)):
            out[i] = prev if prev is not None else np.nan
            continue
        if d is None or (isinstance(d, float) and math.isnan(d)):
            d = 0.0
        if pd_val is None or (isinstance(pd_val, float) and math.isnan(pd_val)):
            pd_val = 0.0

        proximity = min(max(100.0 - (s / p.proximity_divisor * 100.0), 0), 100)
        trend_score = min(max(-d * p.trend_gain, p.trend_floor), p.trend_ceiling)

        # Pressure with more relaxed threshold for 12h window
        # (slower changes over longer period)
        if abs(pd_val) < 0.1:  # More relaxed threshold
            pressure_score = 0.0
        else:
            pressure_score = min(max(-pd_val * p.pressure_gain,
                                     p.pressure_floor),
                                 p.pressure_ceiling)

        if use_pressure:
            raw = (proximity * p.proximity_weight +
                   trend_score * p.trend_weight +
                   pressure_score * p.pressure_weight)
        else:
            raw = (proximity * p.proximity_weight +
                   trend_score * p.trend_weight)

        ceiling = 100.0 if s < p.dry_spread_cutoff else p.dry_ceiling
        raw = min(max(raw, 0), ceiling)

        if prev is None:
            total = raw
        elif raw > prev:
            total = raw
        else:
            total = prev - (prev - raw) * p.hysteresis_decay
        out[i] = total
        prev = total

    return pd.Series(out, index=df.index).round(0)


def model_pressure_lagged(ctx: ModelContext,
                         p: ModelParams | None = None) -> pd.Series:
    """Variant C: Lagged pressure as predictor.
    
    Hypothesis: Pressure changes 6 hours ago predict rain now. This accounts
    for the time it takes for a weather system to arrive after pressure drop.
    
    Implementation:
    - Use pressure from 6h ago
    - Calculate derivative on that lagged series
    - If pressure was falling 6h ago, rain is likely now
    """
    if p is None:
        p = ModelParams()

    df = pd.DataFrame({
        "spread": ctx.spread,
        "deriv": ctx.spread_deriv,
    }).sort_index()
    df["spread"] = df["spread"].ffill()
    df["deriv"] = df["deriv"].fillna(0.0)

    use_pressure = ctx.pressure is not None and not ctx.pressure.dropna().empty
    if use_pressure:
        p_aligned = ctx.pressure.reindex(df.index).ffill()
        # Key change: lag pressure by 6 hours
        p_lagged = p_aligned.shift(freq="6h")
        df["pres_deriv"] = derivative(p_lagged, window=p.pressure_window)
        df["pres_deriv"] = df["pres_deriv"].fillna(0.0)

    out = np.full(len(df), np.nan)
    prev = None
    spread_v = df["spread"].values
    deriv_v = df["deriv"].values
    pres_v = df["pres_deriv"].values if use_pressure else np.zeros(len(df))

    for i in range(len(df)):
        s = spread_v[i]
        d = deriv_v[i]
        pd_val = pres_v[i]

        if s is None or (isinstance(s, float) and math.isnan(s)):
            out[i] = prev if prev is not None else np.nan
            continue
        if d is None or (isinstance(d, float) and math.isnan(d)):
            d = 0.0
        if pd_val is None or (isinstance(pd_val, float) and math.isnan(pd_val)):
            pd_val = 0.0

        proximity = min(max(100.0 - (s / p.proximity_divisor * 100.0), 0), 100)
        trend_score = min(max(-d * p.trend_gain, p.trend_floor), p.trend_ceiling)

        if abs(pd_val) < abs(p.pressure_drop_threshold):
            pressure_score = 0.0
        else:
            pressure_score = min(max(-pd_val * p.pressure_gain,
                                     p.pressure_floor),
                                 p.pressure_ceiling)

        if use_pressure:
            raw = (proximity * p.proximity_weight +
                   trend_score * p.trend_weight +
                   pressure_score * p.pressure_weight)
        else:
            raw = (proximity * p.proximity_weight +
                   trend_score * p.trend_weight)

        ceiling = 100.0 if s < p.dry_spread_cutoff else p.dry_ceiling
        raw = min(max(raw, 0), ceiling)

        if prev is None:
            total = raw
        elif raw > prev:
            total = raw
        else:
            total = prev - (prev - raw) * p.hysteresis_decay
        out[i] = total
        prev = total

    return pd.Series(out, index=df.index).round(0)


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

    df = pd.DataFrame({
        "spread": ctx.spread,
        "deriv": ctx.spread_deriv,
    }).sort_index()
    df["spread"] = df["spread"].ffill()
    df["deriv"] = df["deriv"].fillna(0.0)

    use_pressure = ctx.pressure is not None and not ctx.pressure.dropna().empty
    if use_pressure:
        p_aligned = ctx.pressure.reindex(df.index).ffill()
        
        # Multiple pressure signals
        # 1. Long-term trend (12h window)
        df["pres_long"] = derivative(p_aligned, window="12h").fillna(0.0)
        
        # 2. Short-term trend (3h window, lagged by 3h)
        p_lagged = p_aligned.shift(freq="3h")
        df["pres_short"] = derivative(p_lagged, window="3h").fillna(0.0)
        
        # 3. Absolute pressure
        df["pres_abs"] = p_aligned

    out = np.full(len(df), np.nan)
    prev = None
    spread_v = df["spread"].values
    deriv_v = df["deriv"].values
    
    if use_pressure:
        pres_long_v = df["pres_long"].values
        pres_short_v = df["pres_short"].values
        pres_abs_v = df["pres_abs"].values
    else:
        pres_long_v = np.zeros(len(df))
        pres_short_v = np.zeros(len(df))
        pres_abs_v = np.full(len(df), 1013.25)

    for i in range(len(df)):
        s = spread_v[i]
        d = deriv_v[i]
        p_long = pres_long_v[i]
        p_short = pres_short_v[i]
        p_abs = pres_abs_v[i]

        if s is None or (isinstance(s, float) and math.isnan(s)):
            out[i] = prev if prev is not None else np.nan
            continue
        if d is None or (isinstance(d, float) and math.isnan(d)):
            d = 0.0
        if p_long is None or (isinstance(p_long, float) and math.isnan(p_long)):
            p_long = 0.0
        if p_short is None or (isinstance(p_short, float) and math.isnan(p_short)):
            p_short = 0.0
        if p_abs is None or (isinstance(p_abs, float) and math.isnan(p_abs)):
            p_abs = 1013.25

        proximity = min(max(100.0 - (s / p.proximity_divisor * 100.0), 0), 100)
        trend_score = min(max(-d * p.trend_gain, p.trend_floor), p.trend_ceiling)

        # Long-term pressure trend
        if abs(p_long) < 0.1:
            long_score = 0.0
        else:
            long_score = min(max(-p_long * 15.0, -15.0), 25.0)
        
        # Short-term lagged pressure
        if abs(p_short) < 0.3:
            short_score = 0.0
        else:
            short_score = min(max(-p_short * 20.0, -10.0), 20.0)
        
        # Absolute pressure bonus
        abs_bonus = 0.0
        if use_pressure:
            if p_abs < 990:
                abs_bonus = 15.0
            elif p_abs < 1000:
                abs_bonus = 8.0
            elif p_abs < 1005:
                abs_bonus = 4.0

        if use_pressure:
            raw = (proximity * p.proximity_weight +
                   trend_score * p.trend_weight +
                   long_score * 0.25 +
                   short_score * 0.20 +
                   abs_bonus * 0.20)
        else:
            raw = (proximity * p.proximity_weight +
                   trend_score * p.trend_weight)

        ceiling = 100.0 if s < p.dry_spread_cutoff else p.dry_ceiling
        raw = min(max(raw, 0), ceiling)

        if prev is None:
            total = raw
        elif raw > prev:
            total = raw
        else:
            total = prev - (prev - raw) * p.hysteresis_decay
        out[i] = total
        prev = total

    return pd.Series(out, index=df.index).round(0)


# Export variants for use in analysis scripts
PRESSURE_VARIANTS = {
    "pressure_absolute": model_pressure_absolute,
    "pressure_long_window": model_pressure_long_window,
    "pressure_lagged": model_pressure_lagged,
    "pressure_combined": model_pressure_combined,
}
