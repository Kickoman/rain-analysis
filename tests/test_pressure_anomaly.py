"""
Tests for the station-relative pressure bonus.

The bonus used fixed cut-offs of 990/1000/1005 hPa, which describe *sea-level*
pressure. The barometer sits at ~220 m, where station pressure has a median of
989.6 and never exceeds 1001.1. Measured over 770 hours the old function
returned 20 for 51.8% of them, 10 for 46.6%, 5 for 1.6%, and zero never — a
near-constant +15 offset presented as a cyclone detector, which also shifted
every score against the fixed 50% decision threshold.

An anomaly against the station's own trailing median needs no elevation
constant and follows the seasonal cycle.
"""

import math

import numpy as np
import pandas as pd
import pytest

from pressure_variants import (PRESSURE_ANOMALY_BONUS, SPREAD_FFILL_LIMIT,
                               _abs_pressure_bonus, _setup_dataframe,
                               pressure_anomaly)
from rainlib import ModelContext


def hourly(values, start="2026-07-01"):
    idx = pd.date_range(start, periods=len(values), freq="1h", tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


# ---------------------------------------------------------------------------
# The bonus itself
# ---------------------------------------------------------------------------

def test_normal_pressure_scores_nothing():
    """The property the old thresholds could never satisfy locally."""
    assert _abs_pressure_bonus(0.0) == 0.0
    assert _abs_pressure_bonus(+5.0) == 0.0


def test_bonus_grows_as_pressure_falls_below_normal():
    assert _abs_pressure_bonus(-2.0) == 5.0
    assert _abs_pressure_bonus(-5.0) == 10.0
    assert _abs_pressure_bonus(-10.0) == 20.0


def test_thresholds_are_ordered_and_monotone():
    thresholds = [t for t, _ in PRESSURE_ANOMALY_BONUS]
    bonuses = [b for _, b in PRESSURE_ANOMALY_BONUS]
    assert thresholds == sorted(thresholds)
    assert bonuses == sorted(bonuses, reverse=True)


def test_missing_pressure_scores_nothing_rather_than_guessing():
    """The old code substituted 1013.25 hPa — a sea-level standard the station never sees."""
    assert _abs_pressure_bonus(float("nan")) == 0.0
    assert _abs_pressure_bonus(None) == 0.0


def test_bonus_is_not_saturated_on_realistic_station_pressure():
    """The regression this replaces: with real local readings it must vary."""
    rng = np.random.default_rng(0)
    # Minsk station pressure: median ~989.6, sd ~5
    pressure = hourly(rng.normal(989.6, 5.0, 24 * 60))
    bonuses = pressure_anomaly(pressure).map(_abs_pressure_bonus).dropna()

    zero_share = (bonuses == 0).mean()
    max_share = (bonuses == 20).mean()

    assert zero_share > 0.5, "a bonus that never returns zero is a constant, not a signal"
    assert max_share < 0.2, "'deep cyclone' must be rare, not the modal hour"


# ---------------------------------------------------------------------------
# The anomaly
# ---------------------------------------------------------------------------

def test_anomaly_is_zero_for_steady_pressure():
    result = pressure_anomaly(hourly([1000.0] * 200))
    assert result.dropna().abs().max() == pytest.approx(0.0)


def test_anomaly_is_elevation_independent():
    """A station 25 hPa lower everywhere reports the same anomalies."""
    rng = np.random.default_rng(1)
    base = rng.normal(0, 4, 24 * 45)
    sea_level = pressure_anomaly(hourly(1013 + base))
    station = pressure_anomaly(hourly(988 + base))

    pd.testing.assert_series_equal(sea_level, station, atol=1e-9)


def test_anomaly_uses_only_past_data():
    """A future crash in pressure must not colour earlier rows."""
    calm = [1000.0] * 100
    result_without = pressure_anomaly(hourly(calm))
    result_with = pressure_anomaly(hourly(calm + [960.0] * 20))

    pd.testing.assert_series_equal(result_without.iloc[:100], result_with.iloc[:100])


def test_anomaly_is_unknown_before_enough_history():
    """NaN reads downstream as 'no signal', not as a reading of zero."""
    assert pressure_anomaly(hourly([1000.0] * 10)).isna().all()


def test_a_sustained_low_still_reads_as_low():
    """A multi-day low must not be normalised away by its own baseline."""
    pressure = hourly([1000.0] * 24 * 40 + [986.0] * 24 * 2)
    assert pressure_anomaly(pressure).iloc[-1] < -8.0


# ---------------------------------------------------------------------------
# Bounded forward fill
# ---------------------------------------------------------------------------

def _ctx_with_gap(gap_hours):
    idx = pd.date_range("2026-07-01", periods=gap_hours + 2, freq="1h", tz="UTC")
    spread = pd.Series([4.0] + [np.nan] * gap_hours + [4.0], index=idx)
    return ModelContext(spread=spread, spread_deriv=pd.Series(0.0, index=idx))


def test_short_sensor_gap_is_filled():
    df = _setup_dataframe(_ctx_with_gap(2))
    assert df["spread"].notna().all()


def test_dead_sensor_stops_filling():
    """Unbounded fill let one last reading propagate through the whole run."""
    gap = int(SPREAD_FFILL_LIMIT.total_seconds() // 3600) + 4
    df = _setup_dataframe(_ctx_with_gap(gap))

    assert df["spread"].isna().any()
    assert df["spread"].iloc[-1] == 4.0     # the later real reading still lands


def test_all_missing_spread_does_not_crash():
    idx = pd.date_range("2026-07-01", periods=5, freq="1h", tz="UTC")
    ctx = ModelContext(spread=pd.Series(np.nan, index=idx),
                       spread_deriv=pd.Series(np.nan, index=idx))
    df = _setup_dataframe(ctx)

    assert df["spread"].isna().all()
    assert (df["deriv"] == 0.0).all()
