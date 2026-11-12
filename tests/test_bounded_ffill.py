"""
test_bounded_ffill.py — Tests for bounded forward-fill (issue #453).

A dead barometer or spread sensor must not keep feeding the model for days.
The fill is bounded by time:

* spread   -> SPREAD_FFILL_LIMIT (3h)
* pressure -> STATE_FFILL_LIMIT (6h)

Beyond the limit the cell becomes NaN, so the model emits NaN (no opinion)
instead of a stale carried-forward score, and the row drops out of
``confusion_at_threshold`` / ``roc_auc`` downstream.
"""

import numpy as np
import pandas as pd
import pytest

from rainlib import (
    ModelContext,
    SPREAD_FFILL_LIMIT,
    STATE_FFILL_LIMIT,
    _bounded_ffill,
    model_pressure_aware,
    model_trend_dominant,
    model_tuned,
)
from pressure_variants import _align_pressure


def _idx(n=16):
    return pd.date_range("2026-07-01", periods=n, freq="1h", tz="UTC")


def _spread_gap_ctx(gap_hours):
    """2 valid hours, a gap, then 2 valid hours of spread; deriv is flat 0."""
    idx = _idx(2 + gap_hours + 2)
    spread = pd.Series([2.0, 2.0] + [np.nan] * gap_hours + [2.0, 2.0], index=idx)
    deriv = pd.Series([0.0] * len(idx), index=idx)
    return ModelContext(spread=spread, spread_deriv=deriv)


def _pressure_gap_ctx(gap_hours):
    """2 valid hours, a pressure gap, then 2 valid hours; spread stays flat."""
    idx = _idx(2 + gap_hours + 2)
    spread = pd.Series([3.0] * len(idx), index=idx)
    deriv = pd.Series([0.0] * len(idx), index=idx)
    pressure = pd.Series(
        [1010.0, 1009.0] + [np.nan] * gap_hours + [1008.0, 1007.0], index=idx
    )
    return ModelContext(spread=spread, spread_deriv=deriv, pressure=pressure)


# ---------------------------------------------------------------------------
# The helper itself
# ---------------------------------------------------------------------------

def test_bounded_ffill_fills_short_gap():
    idx = _idx(4)
    s = pd.Series([1.0, np.nan, np.nan, 4.0], index=idx)  # 2h gap, within 3h
    out = _bounded_ffill(s, SPREAD_FFILL_LIMIT)
    assert out.notna().all()


def test_bounded_ffill_stops_after_limit():
    idx = _idx(16)
    s = pd.Series([1.0, 1.0] + [np.nan] * 12 + [4.0, 4.0], index=idx)
    out = _bounded_ffill(s, SPREAD_FFILL_LIMIT)
    # last valid at h1; filled within 3h (h2..h4), then NaN until the next real
    # reading at h14.
    assert out.iloc[2:5].notna().all()
    assert out.iloc[5:14].isna().all()
    assert out.iloc[14] == 4.0


def test_bounded_ffill_integer_index_falls_back_to_plain_ffill():
    s = pd.Series([1.0, np.nan, 3.0], index=[0, 1, 2])
    out = _bounded_ffill(s, SPREAD_FFILL_LIMIT)
    assert out.tolist() == [1.0, 1.0, 3.0]


def test_bounded_ffill_uses_pressure_limit_for_state():
    idx = _idx(16)
    s = pd.Series([1000.0, 1000.0] + [np.nan] * 12 + [1001.0, 1001.0], index=idx)
    out = _bounded_ffill(s, STATE_FFILL_LIMIT)
    # 6h limit: filled through h7, NaN h8..h13
    assert out.iloc[2:8].notna().all()
    assert out.iloc[8:14].isna().all()
    assert out.iloc[14] == 1001.0


# ---------------------------------------------------------------------------
# _align_pressure
# ---------------------------------------------------------------------------

def test_align_pressure_bounded():
    ctx = _pressure_gap_ctx(12)
    df = pd.DataFrame({"spread": ctx.spread, "deriv": ctx.spread_deriv}).sort_index()
    aligned, use = _align_pressure(ctx, df)
    assert use is True
    # last valid pressure at h1 (1009.0); 6h limit -> filled through h7
    assert aligned.iloc[7] == 1009.0
    assert aligned.iloc[8:14].isna().all()
    assert aligned.iloc[14] == 1008.0


# ---------------------------------------------------------------------------
# Models: dead spread sensor -> NaN, not a carried-forward constant
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model", [model_tuned, model_trend_dominant])
def test_spread_gap_yields_nan_not_constant(model):
    ctx = _spread_gap_ctx(12)
    out = model(ctx)
    # within the fill limit the model still scores
    assert out.iloc[:5].notna().all()
    # beyond the 3h limit the output is NaN, not a carried-forward constant
    assert out.iloc[5:14].isna().all()
    # after the gap the model re-seeds with a fresh (non-NaN) score
    assert out.iloc[14:].notna().all()


def test_pressure_aware_pressure_gap_degrades_gracefully():
    ctx = _pressure_gap_ctx(12)
    out = model_pressure_aware(ctx)
    # spread is intact, so the model still scores on spread alone; the key
    # property is that stale pressure neither crashes nor invents a signal.
    assert out.notna().all()
    assert (out >= 0).all() and (out <= 100).all()
