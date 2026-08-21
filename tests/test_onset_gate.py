"""Tests for model_onset_gate — the onset-specialist model.

The project's stated goal is predicting when rain BEGINS, hours ahead — not
whether it is raining. Every spread-led model measures at or below chance on
that transition (the spread derivative is anti-correlated with onsets at dry
hours), so this model deliberately contains no spread term: pressure anomaly,
fall-from-peak, humidity, and the 3-hour temperature trend, through a logistic
frozen on 2021–2025 reanalysis. Validated held-out: front-3h AUC 0.706
(reanalysis 2025–26) and 0.739 (local sensors) versus 0.54–0.61 for every
other registered model.
"""

import numpy as np
import pandas as pd
import pytest

import rainlib as rl
from pressure_variants import (ONSET_GATE_COEF, PRESSURE_VARIANTS,
                               _relative_humidity_from_spread, model_onset_gate)


def _idx(n=72):
    return pd.date_range("2026-07-01", periods=n, freq="1h", tz="UTC")


def _ctx(spread=3.0, pressure=None, temp=None, n=72):
    idx = _idx(n)
    series = lambda v: None if v is None else (
        v.reindex(idx) if isinstance(v, pd.Series) else pd.Series(v, index=idx))
    return rl.ModelContext(
        spread=series(spread), spread_deriv=pd.Series(0.0, index=idx),
        pressure=series(pressure), temp=series(temp))


def test_registered_everywhere():
    assert "onset_gate" in PRESSURE_VARIANTS
    assert "onset_gate" in rl.MODELS


def test_output_is_percent_range():
    idx = _idx()
    out = model_onset_gate(_ctx(pressure=pd.Series(995.0, index=idx),
                                temp=pd.Series(18.0, index=idx)))
    assert out.min() >= 0 and out.max() <= 100
    assert out.notna().all()


def test_pre_frontal_scores_above_ridge_weather():
    """Falling low pressure + moist + warming must outrank rising dry air."""
    idx = _idx()
    pre_front = model_onset_gate(_ctx(
        spread=1.5,
        pressure=pd.Series(996 - np.linspace(0, 8, 72), index=idx),
        temp=pd.Series(16 + np.linspace(0, 3, 72), index=idx)))
    ridge = model_onset_gate(_ctx(
        spread=9.0,
        pressure=pd.Series(1000 + np.linspace(0, 4, 72), index=idx),
        temp=pd.Series(24 - np.linspace(0, 2, 72), index=idx)))
    assert pre_front.iloc[-1] > ridge.iloc[-1] + 20


def test_no_spread_derivative_influence():
    """The one signal the model must NOT use: it is anti-correlated with onsets."""
    idx = _idx()
    base = _ctx(pressure=pd.Series(995.0, index=idx), temp=pd.Series(18.0, index=idx))
    narrowing = rl.ModelContext(spread=base.spread, spread_deriv=pd.Series(-2.0, index=idx),
                                pressure=base.pressure, temp=base.temp)
    assert model_onset_gate(base).equals(model_onset_gate(narrowing))


def test_graceful_without_pressure():
    out = model_onset_gate(_ctx(pressure=None, temp=pd.Series(18.0, index=_idx())))
    assert out.notna().all()
    assert out.max() <= 100


def test_graceful_without_temperature():
    out = model_onset_gate(_ctx(pressure=pd.Series(995.0, index=_idx()), temp=None))
    assert out.notna().all()


def test_stateless():
    idx = _idx()
    ctx = _ctx(pressure=pd.Series(995 - np.linspace(0, 5, 72), index=idx),
               temp=pd.Series(18.0, index=idx))
    assert model_onset_gate(ctx).equals(model_onset_gate(ctx))


def test_rh_inversion_round_trips():
    temp = pd.Series([5.0, 15.0, 25.0, 30.0])
    rh_true = pd.Series([35.0, 60.0, 85.0, 99.0])
    spread = pd.Series(rl.dew_point_spread(temp, rh_true))
    rh_back = _relative_humidity_from_spread(temp, spread)
    assert np.allclose(rh_back, rh_true, atol=0.5)


def test_leading_pressure_gap_does_not_crash():
    idx = _idx()
    pres = pd.Series(995.0, index=idx); pres.iloc[:30] = np.nan
    out = model_onset_gate(_ctx(pressure=pres, temp=pd.Series(18.0, index=idx)))
    assert len(out) == 72


def test_coefficients_are_the_frozen_fit():
    """A silent refit would invalidate the documented held-out scores."""
    assert ONSET_GATE_COEF["anom"] == pytest.approx(-0.0648)
    assert ONSET_GATE_COEF["temp_d3"] == pytest.approx(0.7231)
