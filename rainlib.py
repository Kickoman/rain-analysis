"""
rainlib.py — Rain-prediction backtesting toolkit
=================================================

Reusable building blocks for analysing your Home Assistant rain-probability
model against ground truth (open-meteo) and a third-party forecast (Yandex).

Design goals
------------
* Every Home Assistant helper you built (dew point, spread, derivative,
  rain_probability) is reimplemented here as a *pure Python function* so you
  can replay history and see how parameter changes would have behaved.
* Everything is resampled onto one common time grid so local sensors,
  open-meteo, and Yandex line up hour-by-hour.
* No external services are required at run time — you feed it the files/JSON
  you already collect.

Author: built for your HA weather-station project.
"""

from __future__ import annotations

import json
import glob
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 1. PHYSICS PRIMITIVES  (mirror your HA templates exactly)
# ---------------------------------------------------------------------------

# Magnus coefficients — same values used in your HA dew point template.
MAGNUS_A = 17.62
MAGNUS_B = 243.12


def dew_point(temp_c, rh_pct):
    """Dew point (°C) from temperature (°C) and relative humidity (%).

    Identical to your HA `Outside Dew Point` template:
        alpha = ln(rh/100) + a*t/(b+t)
        dp    = b*alpha / (a-alpha)
    Vectorised: accepts scalars or numpy arrays / pandas Series.
    """
    t = np.asarray(temp_c, dtype=float)
    rh = np.asarray(rh_pct, dtype=float)
    # guard against rh<=0 which would blow up the log
    rh = np.clip(rh, 1e-3, 100.0)
    alpha = np.log(rh / 100.0) + (MAGNUS_A * t) / (MAGNUS_B + t)
    dp = (MAGNUS_B * alpha) / (MAGNUS_A - alpha)
    return dp


def dew_point_spread(temp_c, rh_pct):
    """Temp minus dew point (°C). Small spread => air near saturation."""
    return np.asarray(temp_c, dtype=float) - dew_point(temp_c, rh_pct)


def absolute_humidity(temp_c, rh_pct):
    """Absolute humidity g/m³ — mirrors your HA absolute-humidity template."""
    t = np.asarray(temp_c, dtype=float)
    rh = np.clip(np.asarray(rh_pct, dtype=float), 1e-3, 100.0)
    vp = 6.112 * np.exp(MAGNUS_A * t / (MAGNUS_B + t)) * rh / 100.0
    return 216.7 * vp / (273.15 + t)


def humidex(temp_c, dewpoint_c):
    """Humidex 'feels like' (°C) — mirrors your HA humidex template."""
    t = np.asarray(temp_c, dtype=float)
    td = np.asarray(dewpoint_c, dtype=float)
    vp = 6.112 * np.exp(MAGNUS_A * td / (MAGNUS_B + td))
    return t + 0.5555 * (vp - 10.0)


# ---------------------------------------------------------------------------
# 2. DERIVATIVE  (mirror of HA "Derivative" helper)
# ---------------------------------------------------------------------------

def derivative(series: pd.Series, window: str = "3h", min_periods: int = 2,
                max_gap: str | None = None) -> pd.Series:
    """Approximate HA's Derivative helper.

    HA's Derivative helper fits a linear regression (least-squares slope)
    over a trailing time window and reports the slope per `unit_time`
    (here: °C per hour). This reproduces that behaviour on an irregular
    time index.

    Handles irregular timestamps correctly by computing least-squares
    slope over actual time deltas. If data has gaps, slope is computed
    over the available samples within the window.

    Parameters
    ----------
    series : pd.Series indexed by tz-aware DatetimeIndex
    window : trailing time window, e.g. "1h", "3h"
    min_periods : minimum points required in the window to emit a slope
    max_gap : if set, reject windows where any gap between consecutive
              samples exceeds this duration (e.g. "1h"). Useful when
              sensor downtime creates unreliable slope estimates.

    Returns
    -------
    pd.Series (°C per hour) aligned to `series.index`.
    """
    s = series.dropna()
    if s.empty:
        return pd.Series(index=series.index, dtype=float)

    max_gap_sec = pd.Timedelta(max_gap).total_seconds() if max_gap is not None else None

    # seconds since first sample, as the regression x-axis
    t0 = s.index[0]
    x_all = np.array([(ix - t0).total_seconds() for ix in s.index])
    y_all = s.values.astype(float)
    win_sec = pd.Timedelta(window).total_seconds()

    out = np.full(len(s), np.nan)
    for i in range(len(s)):
        t_now = x_all[i]
        mask = (x_all <= t_now) & (x_all > t_now - win_sec)
        if mask.sum() < min_periods:
            continue
        xs = x_all[mask]
        ys = y_all[mask]
        # reject windows with large gaps (sensor downtime)
        if max_gap_sec is not None and len(xs) >= 2:
            gaps = np.diff(xs)
            if gaps.max() > max_gap_sec:
                continue
        # least-squares slope in units of value per SECOND
        xm = xs.mean()
        denom = ((xs - xm) ** 2).sum()
        if denom == 0:
            continue
        slope_per_sec = ((xs - xm) * (ys - ys.mean())).sum() / denom
        out[i] = slope_per_sec * 3600.0  # -> per hour

    result = pd.Series(out, index=s.index)
    return result.reindex(series.index)


def build_pressure_series_ha(grid: pd.DataFrame,
                             ha_pressure_col: str = "pressure") -> pd.Series | None:
    """Build pressure series from Home Assistant sensor only.
    
    This is the production function — uses only local HA sensor data.
    No fallbacks to external sources.
    
    Parameters
    ----------
    grid : pd.DataFrame
        Unified time grid with pressure data
    ha_pressure_col : str
        Column name for HA pressure (hPa)
    
    Returns
    -------
    pd.Series or None
        Pressure series in hPa, or None if column doesn't exist
    """
    if ha_pressure_col not in grid.columns:
        return None
    
    pressure = grid[ha_pressure_col].copy()
    if pressure.isna().all():
        return None
    return pressure


def build_pressure_series_meteostat(grid: pd.DataFrame,
                                    ms_pres_col: str = "ms_pres") -> pd.Series | None:
    """Build pressure series from Meteostat data only.
    
    For testing/validation purposes. Meteostat provides historical weather
    station data that can be used to validate model behavior on different
    pressure sources.
    
    Parameters
    ----------
    grid : pd.DataFrame
        Unified time grid with pressure data
    ms_pres_col : str
        Column name for Meteostat pressure (hPa)
    
    Returns
    -------
    pd.Series or None
        Pressure series in hPa, or None if column doesn't exist
    """
    if ms_pres_col not in grid.columns:
        return None
    
    pressure = grid[ms_pres_col].copy()
    if pressure.isna().all():
        return None
    return pressure


def build_pressure_series_yandex(grid: pd.DataFrame,
                                 yx_pressure_col: str = "yx_pressure_mm") -> pd.Series | None:
    """Build pressure series from Yandex Weather archive data only.
    
    For testing/validation purposes. Yandex archive provides historical
    forecast data including atmospheric pressure.
    
    Note: Yandex reports pressure in mm Hg, so we convert to hPa:
    hPa = mm Hg × 1.33322
    
    Parameters
    ----------
    grid : pd.DataFrame
        Unified time grid with pressure data
    yx_pressure_col : str
        Column name for Yandex pressure (mm Hg)
    
    Returns
    -------
    pd.Series or None
        Pressure series in hPa, or None if column doesn't exist
    """
    if yx_pressure_col not in grid.columns:
        return None
    
    pressure = grid[yx_pressure_col].copy() * 1.33322  # mm Hg → hPa
    if pressure.isna().all():
        return None
    return pressure


# Backward compatibility: keep old function name but redirect to HA-only
def build_pressure_series(grid: pd.DataFrame,
                          ha_pressure_col: str = "pressure",
                          ms_pres_col: str = "ms_pres",
                          yx_pressure_col: str = "yx_pressure_mm") -> pd.Series | None:
    """Deprecated: Use build_pressure_series_ha() for production.
    
    This function is kept for backward compatibility but now only returns
    HA sensor data (no fallback mixing). For isolated source testing, use:
    - build_pressure_series_ha() — HA sensors only (production)
    - build_pressure_series_meteostat() — Meteostat only (testing)
    - build_pressure_series_yandex() — Yandex only (testing)
    """
    return build_pressure_series_ha(grid, ha_pressure_col)


# Keep the old function available but mark as legacy
def build_pressure_series_legacy(grid: pd.DataFrame,
                                 ha_pressure_col: str = "pressure",
                                 ms_pres_col: str = "ms_pres",
                                 yx_pressure_col: str = "yx_pressure_mm") -> pd.Series | None:
    """Legacy fallback-chain pressure builder (deprecated).
    
    This was the original implementation that mixed sources with fallback.
    Kept for historical comparison only. New code should use isolated functions.
    """
    pressure = pd.Series(index=grid.index, dtype=float)
    if ha_pressure_col in grid.columns:
        pressure = grid[ha_pressure_col].copy()
    if ms_pres_col in grid.columns:
        pressure = pressure.fillna(grid[ms_pres_col])
    if yx_pressure_col in grid.columns:
        pressure = pressure.fillna(grid[yx_pressure_col] * 1.33322)
    if pressure.isna().all():
        return None
    return pressure



# ---------------------------------------------------------------------------
# 3. RAIN-PROBABILITY MODELS  (tunable reimplementations of your HA sensor)
# ---------------------------------------------------------------------------

@dataclass
class ModelParams:
    """All tunable knobs for the rain-probability models, in one place.

    Tweak these in the notebook and re-run to see the effect on history.
    """
    # proximity term
    proximity_divisor: float = 7.0     # spread that maps to 0% proximity
    # trend term
    trend_gain: float = 20.0           # points per (°C/h) of narrowing
    trend_floor: float = -15.0         # most a bad trend can subtract
    trend_ceiling: float = 30.0        # most a good trend can add
    # blend weights
    proximity_weight: float = 0.8
    trend_weight: float = 0.5
    # dryness sanity ceiling
    dry_spread_cutoff: float = 10.0    # above this spread, cap output
    dry_ceiling: float = 40.0
    # pressure-aware parameters
    pressure_weight: float = 0.35       # weight of pressure term in blend
    pressure_gain: float = 25.0         # points per (hPa/h) of pressure drop
    pressure_floor: float = -15.0       # most rising pressure can subtract
    pressure_ceiling: float = 35.0      # most falling pressure can add
    pressure_window: str = "3h"         # trailing window for pressure derivative
    pressure_drop_threshold: float = -0.5  # hPa/h below which pressure signal activates
    # hysteresis (decay fraction toward new lower value each step)
    hysteresis_decay: float = 0.30     # 0 = frozen, 1 = no hysteresis
    # derivative window used to feed the trend term
    derivative_window: str = "3h"


@dataclass
class ModelContext:
    """Unified input context for all models.

    Each model receives the same context and extracts what it needs.
    New data sources (wind, UV, etc.) are added here without changing
    model dispatch code.
    """
    spread: pd.Series
    spread_deriv: pd.Series
    pressure: pd.Series | None = None
    temp: pd.Series | None = None
    abs_humidity: pd.Series | None = None


def _clamp(x, lo, hi):
    return np.minimum(np.maximum(x, lo), hi)


def model_original(ctx: ModelContext,
                   p: ModelParams | None = None) -> pd.Series:
    """Baseline v0.1 model: proximity + trend weighted blend (no hysteresis).

    When ModelParams is provided, uses the parameter values for divisor, gain,
    weights, and trend bounds. When None, falls back to the historical v0.1
    hardcoded defaults for backward compatibility.

    This makes parameter grid tuning meaningful for the 'original' model.
    """
    if p is None:
        # v0.1 historical defaults — preserved for backward compatibility
        divisor = 10.0
        gain = 20.0
        weight_prox = 0.7
        weight_trend = 0.7
        trend_lo = -40.0
        trend_hi = 40.0
    else:
        divisor = p.proximity_divisor
        gain = p.trend_gain
        weight_prox = p.proximity_weight
        weight_trend = p.trend_weight
        trend_lo = p.trend_floor
        trend_hi = p.trend_ceiling

    proximity = _clamp(100.0 - (ctx.spread / divisor * 100.0), 0, 100)
    trend_score = _clamp(-ctx.spread_deriv * gain, trend_lo, trend_hi)
    total = _clamp(proximity * weight_prox + trend_score * weight_trend, 0, 100)
    return total.round(0)


def model_tuned(ctx: ModelContext,
                p: ModelParams | None = None) -> pd.Series:
    """Improved model: recalibrated proximity + capped trend + hysteresis.

    This is a *stateful* model (hysteresis depends on the previous output),
    so it is computed iteratively in time order. All knobs come from `p`.
    """
    if p is None:
        p = ModelParams()

    # align the two inputs on a common index, forward-fill gaps
    df = pd.DataFrame({"spread": ctx.spread, "deriv": ctx.spread_deriv}).sort_index()
    df["spread"] = df["spread"].ffill()
    df["deriv"] = df["deriv"].fillna(0.0)

    out = np.full(len(df), np.nan)
    prev = None  # None until the first valid sample seeds the state
    spread_v = df["spread"].values
    deriv_v = df["deriv"].values

    for i in range(len(df)):
        s = spread_v[i]
        d = deriv_v[i]

        # skip samples with no spread yet (leading gaps / dead sensor)
        if s is None or (isinstance(s, float) and math.isnan(s)):
            out[i] = prev if prev is not None else np.nan
            continue
        if d is None or (isinstance(d, float) and math.isnan(d)):
            d = 0.0

        proximity = min(max(100.0 - (s / p.proximity_divisor * 100.0), 0), 100)
        trend_score = min(max(-d * p.trend_gain, p.trend_floor), p.trend_ceiling)

        raw = proximity * p.proximity_weight + trend_score * p.trend_weight
        # dryness sanity ceiling
        ceiling = 100.0 if s < p.dry_spread_cutoff else p.dry_ceiling
        raw = min(max(raw, 0), ceiling)

        # hysteresis: rise instantly, decay slowly
        if prev is None:
            total = raw
        elif raw > prev:
            total = raw
        else:
            total = prev - (prev - raw) * p.hysteresis_decay
        out[i] = total
        prev = total

    return pd.Series(out, index=df.index).round(0)


def model_trend_dominant(ctx: ModelContext,
                         p: ModelParams | None = None) -> pd.Series:
    """Trend-primary variant (trend is the main driver, spread only a ceiling).

    This is the version discussed for catching the *approach* while a
    3h-window derivative smooths out point noise. Also stateful (hysteresis).
    """
    if p is None:
        p = ModelParams()

    df = pd.DataFrame({"spread": ctx.spread, "deriv": ctx.spread_deriv}).sort_index()
    df["spread"] = df["spread"].ffill()
    df["deriv"] = df["deriv"].fillna(0.0)

    out = np.full(len(df), np.nan)
    prev = None
    spread_v = df["spread"].values
    deriv_v = df["deriv"].values

    for i in range(len(df)):
        s = spread_v[i]
        d = deriv_v[i]

        if s is None or (isinstance(s, float) and math.isnan(s)):
            out[i] = prev if prev is not None else np.nan
            continue
        if d is None or (isinstance(d, float) and math.isnan(d)):
            d = 0.0

        trend_score = min(max(-d * (p.trend_gain * 1.5), -20.0), 100.0)
        ceiling = 100.0 if s < p.dry_spread_cutoff else p.dry_ceiling
        raw = min(max(trend_score, 0), ceiling)

        if prev is None:
            total = raw
        elif raw > prev:
            total = raw
        else:
            total = prev - (prev - raw) * p.hysteresis_decay
        out[i] = total
        prev = total

    return pd.Series(out, index=df.index).round(0)


def model_ha_live(ctx: ModelContext,
                  p: ModelParams | None = None) -> pd.Series:
    """Current Home Assistant production model (no hysteresis, simple weighted blend).

    Formula matches the actual HA template sensor deployed in production:
        proximity = clamp(100 - (spread / 8 * 100), 0, 100)
        trend_score = clamp(-trend * 26.7, -40, 40)
        rain_probability = clamp(proximity * 0.7 + trend_score * 0.7, 0, 100)

    This is stateless (no hysteresis), so each output depends only on current inputs.
    """
    proximity = _clamp(100.0 - (ctx.spread / 8.0 * 100.0), 0, 100)
    trend_score = _clamp(-ctx.spread_deriv * 26.7, -40, 40)
    total = _clamp(proximity * 0.7 + trend_score * 0.7, 0, 100)
    return total.round(0)


def model_pressure_aware(ctx: ModelContext,
                         p: ModelParams | None = None) -> pd.Series:
    """Pressure-aware model: proximity + spread trend + pressure trend.

    Adds atmospheric pressure tendency as a third predictive factor
    alongside spread proximity and spread derivative.

    Meteorology: falling pressure signals an approaching cyclone/storm
    system and is a well-established predictor of precipitation. Rising
    pressure indicates clearing weather (anticyclone).

    If ctx.pressure is None (no pressure data available), falls back to
    the tuned model behaviour (only proximity + trend).

    Stateful (hysteresis on the combined output).
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

        # Pressure: falling pressure adds to rain prob, rising subtracts
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


# Registry so the notebook can loop over models by name.
def _get_pressure_variant(name):
    """Lazy-load pressure variant models to avoid circular imports."""
    from pressure_variants import (model_pressure_absolute, model_pressure_long_window,
                                   model_pressure_lagged, model_pressure_combined,
                                   model_combined)
    variants = {
        "pressure_absolute": model_pressure_absolute,
        "pressure_long_window": model_pressure_long_window,
        "pressure_lagged": model_pressure_lagged,
        "pressure_combined": model_pressure_combined,
        "combined": model_combined,
    }
    return variants[name]


class _LazyModel:
    """Lazy-loading wrapper for pressure variants."""
    def __init__(self, name):
        self._name = name
    
    def __call__(self, *args, **kwargs):
        return _get_pressure_variant(self._name)(*args, **kwargs)


MODELS = {
    "original": model_original,
    "tuned": model_tuned,
    "trend_dominant": model_trend_dominant,
    "ha_live": model_ha_live,
    "pressure_aware": model_pressure_aware,
    "pressure_absolute": _LazyModel("pressure_absolute"),
    "pressure_long_window": _LazyModel("pressure_long_window"),
    "pressure_lagged": _LazyModel("pressure_lagged"),
    "pressure_combined": _LazyModel("pressure_combined"),
    "combined": _LazyModel("combined"),
}


# ---------------------------------------------------------------------------
# 4. DATA LOADERS
# ---------------------------------------------------------------------------

def _parse_ha_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_ha_csv(path: str) -> pd.DataFrame:
    """Load a Home Assistant history CSV export.

    Expects columns: entity_id, state, last_changed.
    Returns a *long* DataFrame with columns [time, entity_id, value],
    dropping unknown/unavailable rows and coercing to float.
    """
    df = pd.read_csv(path)
    df = df[~df["state"].isin(["unknown", "unavailable", ""])].copy()
    df["value"] = pd.to_numeric(df["state"], errors="coerce")
    df = df.dropna(subset=["value"])
    df["time"] = pd.to_datetime(df["last_changed"], utc=True)
    return df[["time", "entity_id", "value"]].sort_values("time")


def ha_wide(df_long: pd.DataFrame, entity_map: dict[str, str]) -> pd.DataFrame:
    """Pivot selected HA entities into wide columns on a shared time index.

    entity_map: {entity_id: friendly_column_name}
    Returns a DataFrame indexed by time with one column per mapped entity.
    Values are placed at their exact timestamps (irregular); resample later.
    """
    parts = []
    for eid, col in entity_map.items():
        sub = df_long[df_long["entity_id"] == eid][["time", "value"]]
        sub = sub.rename(columns={"value": col}).set_index("time")
        parts.append(sub)
    wide = pd.concat(parts, axis=1).sort_index()
    return wide


def load_open_meteo(obj) -> pd.DataFrame:
    """Parse an open-meteo /forecast or /archive JSON response.

    `obj` may be a dict (already parsed), a JSON string, or a path to a
    .json file. Returns a DataFrame indexed by UTC time with whatever of
    temperature_2m / relative_humidity_2m / precipitation / rain / showers
    are present.
    """
    if isinstance(obj, str):
        # path or raw json?
        if obj.strip().startswith("{"):
            try:
                data = json.loads(obj)
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse JSON string: {e}")
        else:
            try:
                with open(obj) as fh:
                    data = json.load(fh)
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse {obj}: malformed JSON - {e}")
            except FileNotFoundError:
                raise ValueError(f"File not found: {obj}")
    else:
        data = obj

    # Validate JSON structure
    if "hourly" not in data:
        raise ValueError("Invalid open-meteo response: missing 'hourly' key")
    
    hourly = data["hourly"]
    tz_offset = data.get("utc_offset_seconds", 0)
    # open-meteo 'time' is in the requested timezone (local). Convert to UTC.
    times_local = pd.to_datetime(hourly["time"])
    times_utc = times_local - pd.to_timedelta(tz_offset, unit="s")
    times_utc = times_utc.tz_localize("UTC")

    cols = {}
    for key in ["temperature_2m", "relative_humidity_2m",
                "precipitation", "rain", "showers"]:
        if key in hourly:
            cols[key] = hourly[key]
    out = pd.DataFrame(cols, index=times_utc)
    out.index.name = "time"
    # friendlier names
    out = out.rename(columns={
        "temperature_2m": "om_temp",
        "relative_humidity_2m": "om_rh",
        "precipitation": "om_precip",
        "rain": "om_rain",
        "showers": "om_showers",
    })
    return out


def load_yandex_archive(folder_or_glob: str) -> pd.DataFrame:
    """Load a folder of Yandex JSON snapshots into a DataFrame.

    Accepts either a directory (searched recursively for *.json) or a glob
    pattern. Extracts the observed `fact` block from each file.
    Returns a DataFrame indexed by UTC observation time.
    """
    if any(ch in folder_or_glob for ch in "*?[]"):
        files = glob.glob(folder_or_glob, recursive=True)
    else:
        files = glob.glob(f"{folder_or_glob.rstrip('/')}/**/*.json", recursive=True)

    rows = {}
    for f in files:
        try:
            d = json.load(open(f))
        except Exception:
            continue
        fact = d.get("fact")
        if not fact:
            continue
        t = datetime.fromtimestamp(d["now"], tz=timezone.utc)
        cond = fact.get("condition", "")
        rows[t] = {
            "yx_condition": cond,
            "yx_temp": fact.get("temp"),
            "yx_humidity": fact.get("humidity"),
            "yx_feels_like": fact.get("feels_like"),
            "yx_prec_prob": fact.get("prec_prob"),
            "yx_prec_strength": fact.get("prec_strength"),
            "yx_pressure_mm": fact.get("pressure_mm"),
            "yx_wind_speed": fact.get("wind_speed"),
            "yx_is_rain": 1 if "rain" in cond else 0,
        }
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    out.index.name = "time"
    return out


def load_meteostat(json_path: str) -> pd.DataFrame:
    """Load Meteostat hourly data from JSON.

    Expects JSON from Meteostat API:
    {
      "meta": {...},
      "data": [
        {"time": "2026-07-05 00:00:00", "temp": 14.5, "prcp": 0.0, "pres": 1007.7, ...},
        ...
      ]
    }

    Returns DataFrame with columns: ms_temp, ms_rhum, ms_precip, ms_pres, ms_dwpt
    """
    try:
        with open(json_path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse {json_path}: malformed JSON ({e})")
    except FileNotFoundError:
        raise ValueError(f"File not found: {json_path}")

    records = data.get("data", [])
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()

    # Rename to ms_ prefix
    rename_map = {
        "temp": "ms_temp",
        "rhum": "ms_rhum",
        "prcp": "ms_precip",
        "pres": "ms_pres",
        "dwpt": "ms_dwpt",
        "wdir": "ms_wdir",
        "wspd": "ms_wspd",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Keep only the columns we renamed
    keep_cols = [v for v in rename_map.values() if v in df.columns]
    return df[keep_cols]


# ---------------------------------------------------------------------------
# 5. UNIFIED TIME GRID
# ---------------------------------------------------------------------------

# Insert before build_grid function (after line 753)

# Precipitation column names that should NOT be forward-filled
# (precipitation is a rate, not a state — gaps should remain NaN)
PRECIP_COLUMNS = {
    'om_precip',
    'ms_precip',
    'om_rain',
    'om_showers',
}

# Condition/state columns that CAN be forward-filled
# (weather conditions persist between observations)
STATE_COLUMNS_ALLOW_FFILL = {
    'yx_condition', 'yx_is_rain', 'yx_prec_prob',
}
def build_grid(ha_wide_df: pd.DataFrame | None = None,
               om_df: pd.DataFrame | None = None,
               yx_df: pd.DataFrame | None = None,
               ms_df: pd.DataFrame | None = None,
               freq: str = "10min",
               ffill_limit_min: int = 90) -> pd.DataFrame:
    """Resample every source onto one regular grid and merge.

    **IMPORTANT FIX (2026-07-18):** Precipitation columns are NO LONGER
    forward-filled. Precipitation is a rate (mm/h), not a state. If it
    rained at 01:00, that does NOT mean it rained at 02:00. Previous
    implementation had a bug that inflated rain hour counts by ~80%.

    New behavior:
    * Local HA sensors (state variables like temp/humidity/pressure) are
      irregular (event-based) -> forward-filled onto the
      grid up to `ffill_limit_min` minutes (so a dead sensor doesn't fill
      forever).
    * open-meteo, Meteostat: hourly data -> reindexed onto the grid
      - Precipitation columns (om_precip, ms_precip, etc.): NO ffill, gaps=NaN
      - State variables (temp, humidity, pressure): ffill up to 6 hours
    * Yandex: hourly snapshots -> reindexed onto grid
      - Condition/state (yx_condition, yx_is_rain): ffill up to 6 hours
      - These are observation states, not rates

    Returns one tidy DataFrame indexed by the regular UTC grid.
    """
    frames = [f for f in (ha_wide_df, om_df, yx_df, ms_df) if f is not None and not f.empty]
    if not frames:
        raise ValueError("No data sources provided to build_grid().")

    start = min(f.index.min() for f in frames)
    end = max(f.index.max() for f in frames)
    grid = pd.date_range(start.floor(freq), end.ceil(freq), freq=freq, tz="UTC")

    limit = int(ffill_limit_min / int(pd.Timedelta(freq).total_seconds() / 60))
    out = pd.DataFrame(index=grid)
    out.index.name = "time"

    if ha_wide_df is not None and not ha_wide_df.empty:
        ha_r = ha_wide_df.sort_index().reindex(
            ha_wide_df.index.union(grid)
        ).ffill(limit=limit).reindex(grid)
        out = out.join(ha_r)

    if om_df is not None and not om_df.empty:
        # Separate precipitation (no ffill) from state variables (ffill)
        om_precip_cols = [c for c in om_df.columns if c in PRECIP_COLUMNS]
        om_state_cols = [c for c in om_df.columns if c not in PRECIP_COLUMNS]
        
        om_r = pd.DataFrame(index=grid)
        if om_precip_cols:
            # Precipitation: reindex only, no forward-fill
            om_precip = om_df[om_precip_cols].sort_index().reindex(grid)
            om_r = om_r.join(om_precip)
        if om_state_cols:
            # State variables: forward-fill up to 6 hours
            om_state = om_df[om_state_cols].sort_index().reindex(
                om_df.index.union(grid)
            ).ffill(limit=6 * (60 // int(pd.Timedelta(freq).total_seconds() / 60))).reindex(grid)
            om_r = om_r.join(om_state)
        out = out.join(om_r)

    if yx_df is not None and not yx_df.empty:
        # Yandex: conditions/states can be forward-filled (weather persists between snapshots)
        yx_r = yx_df.sort_index().reindex(
            yx_df.index.union(grid)
        ).ffill(limit=6 * (60 // int(pd.Timedelta(freq).total_seconds() / 60))).reindex(grid)
        out = out.join(yx_r)

    if ms_df is not None and not ms_df.empty:
        # Separate precipitation (no ffill) from state variables (ffill)
        ms_precip_cols = [c for c in ms_df.columns if c in PRECIP_COLUMNS]
        ms_state_cols = [c for c in ms_df.columns if c not in PRECIP_COLUMNS]
        
        ms_r = pd.DataFrame(index=grid)
        if ms_precip_cols:
            # Precipitation: reindex only, no forward-fill
            ms_precip = ms_df[ms_precip_cols].sort_index().reindex(grid)
            ms_r = ms_r.join(ms_precip)
        if ms_state_cols:
            # State variables: forward-fill up to 6 hours
            ms_state = ms_df[ms_state_cols].sort_index().reindex(
                ms_df.index.union(grid)
            ).ffill(limit=6 * (60 // int(pd.Timedelta(freq).total_seconds() / 60))).reindex(grid)
            ms_r = ms_r.join(ms_state)
        out = out.join(ms_r)

    return out


    if ms_df is not None and not ms_df.empty:
        ms_r = ms_df.sort_index().reindex(
            ms_df.index.union(grid)
        ).ffill(limit=6 * (60 // int(pd.Timedelta(freq).total_seconds() / 60))).reindex(grid)
        out = out.join(ms_r)

    return out


# ---------------------------------------------------------------------------
# 6. GROUND TRUTH LABELS
# ---------------------------------------------------------------------------

def label_rain(grid: pd.DataFrame,
               precip_col: str = "om_precip",
               threshold_mm: float = 0.1) -> pd.Series:
    """Rain label (0/1/NaN) from precipitation data.

    Returns a float Series with:
      - 1.0 : rain detected above threshold
      - 0.0 : no rain detected
      - NaN : unknown (precipitation data missing)

    NaN is preserved instead of fillna(0) — missing precipitation data
    means ground truth is unknown, not "no rain". Scoring functions
    automatically drop NaN rows to avoid penalising the model for
    unknown hours.

    Falls back to Meteostat, then Yandex condition if the primary
    source is unavailable.
    """
    if precip_col in grid and grid[precip_col].notna().any():
        result = (grid[precip_col] >= threshold_mm).astype(float)
        result[grid[precip_col].isna()] = np.nan
        return result
    if "ms_precip" in grid and grid["ms_precip"].notna().any():
        result = (grid["ms_precip"] > 0).astype(float)
        result[grid["ms_precip"].isna()] = np.nan
        return result
    if "yx_is_rain" in grid:
        result = grid["yx_is_rain"].astype(float)
        result[grid["yx_is_rain"].isna()] = np.nan
        return result
    raise ValueError("No precipitation or condition column to label from.")


# ---------------------------------------------------------------------------
# 7. METRICS
# ---------------------------------------------------------------------------

def confusion_at_threshold(pred: pd.Series, truth: pd.Series,
                           threshold: float = 50.0,
                           drop_unknown: bool = True) -> dict:
    """Confusion-matrix counts + rates treating pred>=threshold as 'rain'.

    With drop_unknown=True (default), rows where truth is NaN are
    dropped: unknown ground truth doesn't penalise the model.
    Set to False to treat NaN truth as no-rain (old behaviour).
    """
    df = pd.DataFrame({"pred": pred, "truth": truth})
    if drop_unknown:
        df = df.dropna()
    else:
        df = df.fillna({"truth": 0})
    yhat = (df["pred"] >= threshold).astype(int)
    y = df["truth"].astype(int)
    tp = int(((yhat == 1) & (y == 1)).sum())
    fp = int(((yhat == 1) & (y == 0)).sum())
    tn = int(((yhat == 0) & (y == 0)).sum())
    fn = int(((yhat == 0) & (y == 1)).sum())
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    if precision is None or recall is None or math.isnan(precision) or math.isnan(recall):
        f1 = float("nan")
    elif (precision + recall) == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {
        "threshold": threshold,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "n": len(df),
    }


def sweep_threshold(pred: pd.Series, truth: pd.Series,
                    thresholds=range(5, 100, 5)) -> pd.DataFrame:
    """Compute precision/recall/F1 across a range of thresholds."""
    return pd.DataFrame(
        [confusion_at_threshold(pred, truth, t) for t in thresholds]
    ).set_index("threshold")


def lead_time(pred: pd.Series, truth: pd.Series,
              threshold: float = 50.0) -> pd.Timedelta | None:
    """How long before the first rain hour did pred first cross threshold?

    Positive => early warning. None => never crossed before onset.
    """
    df = pd.DataFrame({"pred": pred, "truth": truth}).dropna().sort_index()
    rain_times = df.index[df["truth"] == 1]
    if len(rain_times) == 0:
        return None
    first_rain = rain_times[0]
    crossed = df.index[(df["pred"] >= threshold) & (df.index <= first_rain)]
    if len(crossed) == 0:
        return None
    return first_rain - crossed[0]


# ---------------------------------------------------------------------------
# 8. THRESHOLD RECOMMENDATION  (formalises the precision/recall trade-off)
# ---------------------------------------------------------------------------

def fbeta_at_threshold(pred: pd.Series, truth: pd.Series,
                       threshold: float, beta: float = 1.0) -> float:
    """F-beta score at a given threshold.

    beta expresses how much more you care about RECALL than PRECISION:
        beta = 1   -> F1, recall and precision weighted equally
        beta = 2   -> recall counts 4x as much as precision
                      ("a miss is much worse than a false alarm")
        beta = 0.5 -> precision counts 4x as much as recall
                      ("a false alarm is much worse than a miss")

    The weighting is beta**2, following the standard F-beta definition.
    Returns NaN when precision+recall is undefined (no positive predictions
    and no positives caught).
    """
    c = confusion_at_threshold(pred, truth, threshold)
    p, r = c["precision"], c["recall"]
    if p != p or r != r:          # NaN guard
        return float("nan")
    b2 = beta * beta
    denom = (b2 * p) + r
    if denom == 0:
        return float("nan")
    return (1 + b2) * p * r / denom


def recommend_threshold(pred: pd.Series, truth: pd.Series,
                        beta: float = 2.0,
                        min_precision: float = 0.0,
                        thresholds=range(5, 100, 5)) -> dict:
    """Pick the threshold that maximises F-beta for your chosen trade-off.

    Parameters
    ----------
    beta : how many times worse a MISSED rain is than a FALSE ALARM.
           beta=2 (default) suits "I'd rather bring the laundry in for
           nothing than get it soaked". Use beta=1 for balanced, beta=0.5
           if false alarms annoy you more than misses.
    min_precision : reject thresholds whose precision falls below this.
           Without a floor, a high beta will always collapse onto the very
           lowest threshold (alert-always), which is useless. Setting e.g.
           0.5 means "at least half my alerts must be real rain" and keeps
           the recommendation practical. Default 0.0 = no floor.

    Returns a dict with the best threshold and its metrics, plus the full
    per-threshold table under key 'table' for inspection/plotting.
    """
    rows = []
    for t in thresholds:
        c = confusion_at_threshold(pred, truth, t)
        rows.append({
            "threshold": t,
            "precision": c["precision"],
            "recall": c["recall"],
            "f1": c["f1"],
            "fbeta": fbeta_at_threshold(pred, truth, t, beta),
            "tp": c["tp"], "fp": c["fp"], "fn": c["fn"], "tn": c["tn"],
        })
    table = pd.DataFrame(rows).set_index("threshold")

    # candidates must clear the precision floor (if any)
    candidates = table.copy()
    if min_precision > 0:
        candidates = candidates[candidates["precision"] >= min_precision]

    # best = highest F-beta; ties broken toward the LOWER threshold
    # (earlier warning) since for rain that's usually the safer side.
    valid = candidates["fbeta"].dropna()
    if valid.empty:
        best_t = None
        best_row = None
    else:
        best_val = valid.max()
        best_t = valid[valid >= best_val - 1e-9].index.min()
        best_row = table.loc[best_t]

    return {
        "beta": beta,
        "min_precision": min_precision,
        "best_threshold": (int(best_t) if best_t is not None else None),
        "precision": (float(best_row["precision"]) if best_row is not None else None),
        "recall": (float(best_row["recall"]) if best_row is not None else None),
        "f1": (float(best_row["f1"]) if best_row is not None else None),
        "fbeta": (float(best_row["fbeta"]) if best_row is not None else None),
        "table": table,
    }


def plot_calibration(pred: pd.Series, truth: pd.Series,
                     betas=(0.5, 1.0, 2.0),
                     thresholds=range(5, 100, 5),
                     ax=None, title: str | None = None):
    """Plot precision / recall / F-beta vs threshold, marking the best pick.

    Draws precision and recall curves, plus one F-beta curve per value in
    `betas`, and drops a vertical marker at each beta's recommended threshold.
    Needs matplotlib; pass an existing `ax` to compose into a larger figure.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        raise ImportError(
            "plot_calibration() requires matplotlib. "
            "Install it with: pip install matplotlib>=3.7"
        )

    if ax is None:
        _, ax = plt.subplots(figsize=(9, 5))

    sw = sweep_threshold(pred, truth, thresholds)
    ax.plot(sw.index, sw["precision"], "o-", color="tab:blue", label="precision")
    ax.plot(sw.index, sw["recall"], "s-", color="tab:orange", label="recall")

    colours = ["tab:green", "tab:red", "tab:purple", "tab:brown"]
    for beta, col in zip(betas, colours):
        rec = recommend_threshold(pred, truth, beta=beta, thresholds=thresholds)
        tbl = rec["table"]
        ax.plot(tbl.index, tbl["fbeta"], "^--", color=col, alpha=0.7,
                label=f"F(beta={beta})")
        bt = rec["best_threshold"]
        if bt is not None:
            ax.axvline(bt, color=col, ls=":", alpha=0.6)
            ax.annotate(f"β={beta}→{bt}",
                        xy=(bt, 0.02), rotation=90, color=col,
                        fontsize=8, va="bottom", ha="right")

    ax.set_xlabel("alert threshold (%)")
    ax.set_ylabel("score")
    ax.set_ylim(0, 1.05)
    ax.legend(loc="upper right", fontsize=8, ncol=2)
    ax.set_title(title or "Threshold calibration")
    return ax
