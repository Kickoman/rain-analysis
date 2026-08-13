"""
Tests for `pressure_primary` — the model that weights signals by measured value.

Every other model here leads with the dew-point-spread derivative, which
measures at ROC AUC 0.492 over 49,200 hours — below chance — while absolute
pressure reaches 0.749 and was used only through a saturated step function.
This model inverts that ordering. On the 43-day archive it reaches the highest
nowcast AUC (0.637) and average precision (0.384) of the physics models.

The tests pin the ordering property rather than the score values, so the model
can be retuned without rewriting them.
"""

import numpy as np
import pandas as pd
import pytest

import rainlib as rl
from pressure_variants import (DIURNAL_AMPLITUDE, DIURNAL_PEAK_HOUR_UTC,
                               W_PRESSURE, W_PROXIMITY, W_TREND,
                               model_pressure_primary)


def ctx(hours=24 * 45, spread=4.0, deriv=0.0, pressure=990.0, start="2026-07-01"):
    idx = pd.date_range(start, periods=hours, freq="1h", tz="UTC")
    as_series = lambda v: pd.Series(v, index=idx, dtype=float) if np.isscalar(v) \
        else pd.Series(v, index=idx, dtype=float)
    return rl.ModelContext(
        spread=as_series(spread),
        spread_deriv=as_series(deriv),
        pressure=None if pressure is None else as_series(pressure),
    )


def run(**kwargs):
    return model_pressure_primary(ctx(**kwargs), rl.ModelParams())


# ---------------------------------------------------------------------------
# The ordering that is the point of the model
# ---------------------------------------------------------------------------

def test_pressure_outweighs_the_spread_derivative():
    assert W_PRESSURE > W_PROXIMITY > W_TREND


def test_falling_pressure_raises_the_score_more_than_a_narrowing_spread():
    """A dropping barometer must matter more than a closing spread."""
    n = 24 * 45
    steady = np.full(n, 990.0)
    falling = np.concatenate([np.full(n - 24, 990.0), np.linspace(990.0, 975.0, 24)])

    from_pressure = model_pressure_primary(
        rl.ModelContext(spread=ctx().spread, spread_deriv=ctx().spread_deriv,
                        pressure=pd.Series(falling, index=ctx().spread.index)),
        rl.ModelParams()).iloc[-1]
    from_trend = model_pressure_primary(
        rl.ModelContext(spread=ctx().spread,
                        spread_deriv=pd.Series(-1.5, index=ctx().spread.index),
                        pressure=pd.Series(steady, index=ctx().spread.index)),
        rl.ModelParams()).iloc[-1]

    assert from_pressure > from_trend


def test_score_rises_as_pressure_falls_below_normal():
    n = 24 * 45
    idx = pd.date_range("2026-07-01", periods=n, freq="1h", tz="UTC")
    scores = []
    for drop in (0.0, 5.0, 12.0):
        pressure = np.full(n, 990.0)
        pressure[-6:] = 990.0 - drop
        scores.append(model_pressure_primary(
            rl.ModelContext(spread=pd.Series(4.0, index=idx),
                            spread_deriv=pd.Series(0.0, index=idx),
                            pressure=pd.Series(pressure, index=idx)),
            rl.ModelParams()).iloc[-1])

    assert scores[0] < scores[1] < scores[2]


def test_dry_air_still_vetoes():
    """No pressure anomaly makes rain out of desert air."""
    n = 24 * 45
    idx = pd.date_range("2026-07-01", periods=n, freq="1h", tz="UTC")
    pressure = np.full(n, 990.0)
    pressure[-6:] = 970.0

    result = model_pressure_primary(
        rl.ModelContext(spread=pd.Series(15.0, index=idx),
                        spread_deriv=pd.Series(0.0, index=idx),
                        pressure=pd.Series(pressure, index=idx)),
        rl.ModelParams()).iloc[-1]

    assert result <= rl.ModelParams().dry_ceiling


# ---------------------------------------------------------------------------
# Diurnal term
# ---------------------------------------------------------------------------

def test_afternoon_scores_above_night():
    """Rain within 3h peaks at 11h UTC (1.32x base) and bottoms near 20h (0.74x)."""
    result = run()
    by_hour = result.groupby(result.index.hour).mean()

    assert by_hour[DIURNAL_PEAK_HOUR_UTC] > by_hour[(DIURNAL_PEAK_HOUR_UTC + 12) % 24]


def test_diurnal_swing_is_bounded():
    """A modifier, not a driver — it must not dominate the physical signals."""
    result = run()
    by_hour = result.groupby(result.index.hour).mean()
    swing = by_hour.max() / by_hour.min()

    assert swing < (1 + DIURNAL_AMPLITUDE) / (1 - DIURNAL_AMPLITUDE) + 0.01


# ---------------------------------------------------------------------------
# Degradation and range
# ---------------------------------------------------------------------------

def test_works_without_pressure():
    """Beyond the barometer's history the model must still produce something."""
    result = run(pressure=None)
    assert result.notna().all()
    assert (result >= 0).all()


def test_output_stays_in_percent_range():
    n = 24 * 45
    idx = pd.date_range("2026-07-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(0)
    result = model_pressure_primary(
        rl.ModelContext(spread=pd.Series(rng.uniform(0, 15, n), index=idx),
                        spread_deriv=pd.Series(rng.normal(0, 2, n), index=idx),
                        pressure=pd.Series(rng.normal(990, 8, n), index=idx)),
        rl.ModelParams())

    assert result.min() >= 0
    assert result.max() <= 100


def test_uses_a_usable_share_of_the_range():
    """The regression the rescaling fixed: crossing 50 on 4.2% of hours."""
    n = 24 * 45
    idx = pd.date_range("2026-07-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(1)
    result = model_pressure_primary(
        rl.ModelContext(spread=pd.Series(rng.uniform(0, 10, n), index=idx),
                        spread_deriv=pd.Series(rng.normal(0, 1, n), index=idx),
                        pressure=pd.Series(rng.normal(990, 6, n), index=idx)),
        rl.ModelParams())

    assert result.quantile(0.9) > 40


def test_has_no_hysteresis():
    """A spike must not leave a decaying tail behind it.

    The stateful variants carry the previous output forward, so one excited hour
    keeps the score elevated for several after it. This model has no such memory:
    every row is a function of that row's inputs alone. (It does depend on
    *preceding data* through the trailing pressure baseline — that is a feature
    window, not carried state.)
    """
    n = 24 * 45
    idx = pd.date_range("2026-07-01", periods=n, freq="1h", tz="UTC")
    spread = pd.Series(4.0, index=idx)
    pressure = pd.Series(990.0, index=idx)

    calm = pd.Series(0.0, index=idx)
    spiked = calm.copy()
    spiked.iloc[-5] = -3.0        # one hour of sharply narrowing spread

    baseline = model_pressure_primary(
        rl.ModelContext(spread=spread, spread_deriv=calm, pressure=pressure), rl.ModelParams())
    result = model_pressure_primary(
        rl.ModelContext(spread=spread, spread_deriv=spiked, pressure=pressure), rl.ModelParams())

    assert result.iloc[-5] > baseline.iloc[-5]
    pd.testing.assert_series_equal(result.iloc[-4:], baseline.iloc[-4:])


def test_identical_inputs_give_identical_scores():
    """Determinism: the same context always yields the same series."""
    context = ctx()
    first = model_pressure_primary(context, rl.ModelParams())
    second = model_pressure_primary(context, rl.ModelParams())
    pd.testing.assert_series_equal(first, second)


def test_registered_in_the_model_registry():
    assert "pressure_primary" in rl.MODELS
    assert rl.MODELS["pressure_primary"](ctx(), rl.ModelParams()).notna().any()
