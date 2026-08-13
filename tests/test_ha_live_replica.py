"""
Tests that the ha_live replica reproduces the deployed Home Assistant model.

The deployed template reads `sensor.outside_dew_point_spread_trend`; the replica
recomputed the derivative in Python over a 3h window. Measured over 10 days of
recorder history the two trend inputs agree only at corr 0.83 (MAE 0.71 °C/h),
which pushed the replica's peak score from 74 down to 58 — enough to stop it
crossing the 50% alert threshold at all, so it scored F1 0.000 against a live
sensor scoring 0.143. Feeding it the recorded trend sensor takes agreement with
production from corr 0.809 / MAE 6.4 to corr 0.998 / MAE 0.3.

Note this was *not* the balcony sensor's temperature/humidity bias: the Python
dew-point spread matches Home Assistant's own spread sensor at corr 1.0000
(MAE 0.026 °C), so production and replica see the same biased input.
"""

import numpy as np
import pandas as pd
import pytest

import rainlib as rl


def _series(values, freq="10min"):
    idx = pd.date_range("2026-08-01", periods=len(values), freq=freq, tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


def _ha_live(spread, deriv, ha_trend=None):
    return rl.model_ha_live(rl.ModelContext(
        spread=_series(spread),
        spread_deriv=_series(deriv),
        ha_spread_trend=None if ha_trend is None else _series(ha_trend),
    ))


# ---------------------------------------------------------------------------
# Input selection
# ---------------------------------------------------------------------------

def test_uses_ha_trend_sensor_when_available():
    """The recorded sensor must win over the recomputed derivative."""
    spread = [4.0] * 5

    from_sensor = _ha_live(spread, deriv=[0.0] * 5, ha_trend=[-1.5] * 5)
    from_deriv = _ha_live(spread, deriv=[-1.5] * 5)

    assert from_sensor.equals(from_deriv)


def test_falls_back_to_computed_derivative():
    """Beyond the recorder window the trend sensor is simply not there."""
    result = _ha_live([4.0] * 5, deriv=[-1.0] * 5, ha_trend=None)
    assert result.notna().all()
    assert result.iloc[0] > 0


def test_gaps_in_the_trend_sensor_fall_back_per_sample():
    """A missing reading means no trend reported, not a dead row."""
    result = _ha_live([4.0] * 4, deriv=[-1.0] * 4, ha_trend=[-1.0, np.nan, np.nan, -1.0])
    assert result.notna().all()


def test_trend_sensor_is_realigned_to_the_spread_index():
    """The two sensors report at different times; misalignment must not drop rows."""
    spread = _series([4.0] * 6)
    deriv = _series([-1.0] * 6)
    trend = pd.Series([-1.5, -1.5], index=spread.index[[1, 3]])

    result = rl.model_ha_live(rl.ModelContext(
        spread=spread, spread_deriv=deriv, ha_spread_trend=trend))

    assert len(result) == 6
    assert result.notna().all()


# ---------------------------------------------------------------------------
# The formula itself still matches the deployed template
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spread,trend,expected", [
    (0.0, 0.0, 70.0),      # proximity 100 * 0.7
    (8.0, 0.0, 0.0),       # proximity floor
    (4.0, 0.0, 35.0),      # proximity 50 * 0.7
    (4.0, -1.5, 63.0),     # + trend clamped to +40, * 0.7
    (4.0, 1.5, 7.0),       # - trend clamped to -40, * 0.7
])
def test_matches_deployed_template(spread, trend, expected):
    result = _ha_live([spread], deriv=[0.0], ha_trend=[trend])
    assert result.iloc[0] == pytest.approx(expected, abs=1.0)


def test_trend_contribution_is_clamped():
    """The template clamps the trend term to +/-40 before weighting."""
    gentle = _ha_live([4.0], deriv=[0.0], ha_trend=[-1.5])
    extreme = _ha_live([4.0], deriv=[0.0], ha_trend=[-15.0])
    assert gentle.iloc[0] == extreme.iloc[0]


def test_output_stays_in_percent_range():
    result = _ha_live([0.0, 2.0, 4.0, 8.0, 12.0], deriv=[0.0] * 5,
                      ha_trend=[-5.0, -2.0, 0.0, 2.0, 5.0])
    assert result.min() >= 0
    assert result.max() <= 100


def test_model_is_stateless():
    """No hysteresis: identical inputs give identical outputs regardless of order."""
    forward = _ha_live([4.0, 2.0, 6.0], deriv=[0.0] * 3, ha_trend=[-1.0, -1.0, -1.0])
    reverse = _ha_live([6.0, 2.0, 4.0], deriv=[0.0] * 3, ha_trend=[-1.0, -1.0, -1.0])
    assert sorted(forward.tolist()) == sorted(reverse.tolist())


# ---------------------------------------------------------------------------
# The regression this guards against
# ---------------------------------------------------------------------------

def test_derivative_mismatch_suppresses_the_alert_threshold():
    """Reproduces the failure: a smoothed derivative keeps the score under 50%.

    Home Assistant's helper reports a sharper trend than a 3h least-squares fit
    over the same data. With the sharper value the score clears the 50% alert
    threshold; with the smoothed one it never does, which is how the replica
    scored zero recall while the live sensor was firing.
    """
    spread = [3.0] * 5
    smoothed = [-0.3] * 5
    sharp = [-1.5] * 5

    assert _ha_live(spread, deriv=smoothed).max() < 50
    assert _ha_live(spread, deriv=smoothed, ha_trend=sharp).max() >= 50
