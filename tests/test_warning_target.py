"""
Tests for the warning target and the baseline floor.

The product is an alert — "it will rain soon" — but every model was scored
against "is it raining this hour". `rainlib_temporal` compensated by bolting
tolerance windows onto the metric; `label_rain_within` builds the horizon into
the label instead, so ordinary precision and recall mean the right thing.

The baselines exist because there was no floor. Measured over 2026-07-01 →
2026-08-13, "always alert" scores F1 0.385 on the nowcast — beating eight of the
ten hand-tuned models — and persistence scores 0.709, beating all of them.
"""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

import rainlib as rl
from run_analysis import (AnalysisConfig, build_baselines, score_baselines,
                          score_warning_target)


def series(values, freq="1h"):
    idx = pd.date_range("2026-07-01", periods=len(values), freq=freq, tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


# ---------------------------------------------------------------------------
# label_rain_within
# ---------------------------------------------------------------------------

def test_marks_the_hours_before_rain():
    labels = series([0, 0, 1, 0, 0, 0])
    result = rl.label_rain_within(labels, 2)
    # hours 0 and 1 see the rain at index 2 within their 2-hour horizon
    assert result.iloc[0] == 1.0
    assert result.iloc[1] == 1.0


def test_raining_now_is_not_the_same_as_will_rain():
    """The distinction the whole change exists for."""
    labels = series([0, 0, 1, 0, 0, 0])
    result = rl.label_rain_within(labels, 2)
    assert labels.iloc[2] == 1.0        # it is raining
    assert result.iloc[2] == 0.0        # but nothing is coming


def test_horizon_length_is_respected():
    labels = series([0, 0, 0, 0, 1])
    assert rl.label_rain_within(labels, 1).iloc[0] == 0.0
    assert rl.label_rain_within(labels, 4).iloc[0] == 1.0


def test_tail_is_unknown_not_dry():
    """Past the end of the data the horizon cannot be evaluated."""
    result = rl.label_rain_within(series([0, 0, 0, 0]), 2)
    assert result.iloc[-2:].isna().all()


def test_unknown_inside_the_horizon_is_unknown():
    labels = series([0, np.nan, 0, 0, 0])
    assert np.isnan(rl.label_rain_within(labels, 2).iloc[0])


def test_known_rain_beats_an_unknown_elsewhere_in_the_horizon():
    """If rain is confirmed inside the window, a gap next to it changes nothing."""
    labels = series([0, 1, np.nan, 0, 0])
    assert rl.label_rain_within(labels, 2).iloc[0] == 1.0


def test_zero_horizon_is_a_passthrough():
    labels = series([0, 1, 0])
    assert rl.label_rain_within(labels, 0).equals(labels)


def test_horizon_scales_with_grid_frequency():
    """Three hours is three hours, whether the grid is hourly or 10-minutely."""
    labels_10min = series([0] * 18 + [1], freq="10min")
    result = rl.label_rain_within(labels_10min, 3, freq="10min")
    assert result.iloc[0] == 1.0        # 18 steps ahead is exactly 3 hours


def test_rejects_a_nonsense_frequency():
    with pytest.raises(ValueError, match="positive duration"):
        rl.label_rain_within(series([0, 1]), 3, freq="0h")


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------

def _grid(**cols):
    n = len(next(iter(cols.values())))
    idx = pd.date_range("2026-07-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({k: np.asarray(v, dtype=float) for k, v in cols.items()}, index=idx)


def test_persistence_uses_only_the_past():
    """It must be what was known an hour ago, never the current hour."""
    grid = _grid(rain_truth=[0, 1, 0, 0])
    persistence = build_baselines(grid)["persistence"]

    assert np.isnan(persistence.iloc[0])
    assert persistence.iloc[1] == 0.0     # hour 0 was dry
    assert persistence.iloc[2] == 100.0   # hour 1 rained


def test_always_alert_is_defined_everywhere():
    grid = _grid(rain_truth=[0, 1, np.nan, 0])
    assert (build_baselines(grid)["always_alert"] == 100.0).all()


def test_always_alert_precision_is_the_base_rate():
    """Its whole purpose: the honest reference for 'is this precision real?'."""
    grid = _grid(rain_truth=[1, 0, 0, 0, 1, 0, 0, 0, 0, 0])
    result = score_baselines(grid, AnalysisConfig(rain_within_hours=0))

    assert result["always_alert"]["nowcast"]["precision"] == pytest.approx(0.2)
    assert result["always_alert"]["nowcast"]["recall"] == pytest.approx(1.0)


def test_yandex_probabilities_are_rescaled_to_percent():
    grid = _grid(rain_truth=[0, 1], yx_prec_prob=[0.2, 0.9])
    assert build_baselines(grid)["yandex_forecast"].max() == pytest.approx(90.0)


def test_yandex_already_in_percent_is_left_alone():
    grid = _grid(rain_truth=[0, 1], yx_prec_prob=[20.0, 90.0])
    assert build_baselines(grid)["yandex_forecast"].max() == pytest.approx(90.0)


def test_yandex_absent_is_simply_omitted():
    assert "yandex_forecast" not in build_baselines(_grid(rain_truth=[0, 1]))


def test_baselines_are_scored_against_both_targets():
    grid = _grid(rain_truth=[0, 0, 1, 0, 0, 1, 0, 0])
    grid["rain_truth_window"] = rl.label_rain_within(grid["rain_truth"], 2)

    result = score_baselines(grid, AnalysisConfig(rain_within_hours=2))
    assert set(result["always_alert"]) == {"nowcast", "within_2h"}


# ---------------------------------------------------------------------------
# Warning-target scoring
# ---------------------------------------------------------------------------

def test_warning_scores_rank_by_auc():
    grid = _grid(rain_truth=[0, 0, 1, 0, 0, 1, 0, 0])
    grid["rain_truth_window"] = rl.label_rain_within(grid["rain_truth"], 2)
    # a model that tracks the horizon, and one that is constant
    grid["model_original"] = grid["rain_truth_window"].fillna(0) * 100
    grid["model_tuned"] = 50.0

    result = score_warning_target(grid, AnalysisConfig(rain_within_hours=2))

    assert result["horizon_hours"] == 2
    assert result["ranked_by"] == "roc_auc"
    assert result["best_model"] == "original"
    assert result["scores"]["tuned"]["roc_auc"] == pytest.approx(0.5)


def test_warning_scoring_disabled_at_zero_horizon():
    grid = _grid(rain_truth=[0, 1], model_original=[10.0, 90.0])
    assert score_warning_target(grid, AnalysisConfig(rain_within_hours=0)) == {}


def test_warning_scoring_needs_labelled_hours():
    grid = _grid(rain_truth=[0, 1], model_original=[10.0, 90.0])
    grid["rain_truth_window"] = np.nan
    assert score_warning_target(grid, AnalysisConfig(rain_within_hours=3)) == {}
