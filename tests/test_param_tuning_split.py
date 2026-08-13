"""
Tests that grid search is selected on the past and reported on the future.

`param_tuning` used to fit and report on the same rows, so its headline "best
F1" was the maximum of 36 draws against one window — a number that describes the
size of the grid more than the quality of the parameters. On the 43-day archive
the difference is not subtle: selection F1 0.429, held-out F1 0.161.
"""

import numpy as np
import pandas as pd
import pytest

from run_analysis import AnalysisConfig, param_tuning


def make_grid(n=400, seed=0):
    """A grid with enough labelled hours to split, and no real signal.

    Deliberately unpredictable: any apparent skill the search finds is fitting
    noise, which is exactly what the holdout figure should reveal.
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-07-01", periods=n, freq="1h", tz="UTC")
    grid = pd.DataFrame(index=idx)
    grid["spread"] = rng.uniform(0, 12, n)
    grid["spread_deriv"] = rng.normal(0, 1, n)
    grid["rain_truth"] = (rng.random(n) < 0.25).astype(float)
    return grid


def test_reports_a_split_point():
    result = param_tuning(make_grid(), AnalysisConfig())
    validation = result["validation"]

    assert validation["split_at"] is not None
    assert validation["train_frac"] == 0.7


def test_every_candidate_carries_a_holdout_score():
    result = param_tuning(make_grid(), AnalysisConfig())

    for candidate in result["top_15"]:
        assert "holdout" in candidate
        assert candidate["holdout"] is not None
        assert "f1" in candidate["holdout"]


def test_selection_and_holdout_are_measured_on_different_rows():
    grid = make_grid()
    result = param_tuning(grid, AnalysisConfig())
    best = result["best_params"]

    labelled = int(grid["rain_truth"].notna().sum())
    assert best["holdout"]["n"] < labelled
    assert best["holdout"]["n"] > 0


def test_selection_score_is_optimistic_on_noise():
    """With no real signal, the winner's advantage should not survive the split."""
    result = param_tuning(make_grid(seed=3), AnalysisConfig())
    validation = result["validation"]

    assert validation["selection_f1"] is not None
    assert validation["holdout_f1"] is not None
    assert validation["holdout_f1"] <= validation["selection_f1"]


def test_ranking_still_uses_the_selection_score():
    """top_15 must be ordered by the score the search actually optimised."""
    result = param_tuning(make_grid(), AnalysisConfig())
    f1s = [c["f1"] for c in result["top_15"] if c["f1"] is not None]

    assert f1s == sorted(f1s, reverse=True)


def test_too_few_labelled_hours_skips_the_split_and_says_so():
    """Better to report one honest caveat than to split three rows."""
    grid = make_grid(n=12)
    result = param_tuning(grid, AnalysisConfig())

    assert result["validation"]["split_at"] is None
    assert "optimistic" in result["validation"]["note"]
    assert result["best_params"]["holdout"] is None


def test_unlabelled_hours_do_not_move_the_split():
    """The split is placed by labelled hours, not by row count."""
    grid = make_grid(n=200)
    grid.loc[grid.index[:100], "rain_truth"] = np.nan

    split_at = pd.Timestamp(param_tuning(grid, AnalysisConfig())["validation"]["split_at"])
    assert split_at > grid.index[100]


def test_historical_keys_are_preserved():
    """Report code and older tests read these names."""
    result = param_tuning(make_grid(), AnalysisConfig())

    assert set(result) >= {"total_combinations", "best_params", "top_15", "validation"}
    assert set(result["best_params"]) >= {"proximity_divisor", "hysteresis_decay",
                                          "trend_gain", "precision", "recall", "f1"}
