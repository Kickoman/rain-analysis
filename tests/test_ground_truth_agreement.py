"""
Tests for ground-truth source agreement.

Open-Meteo is reanalysis of a model grid cell, Meteostat a real station some km
away, Yandex a spot observation. Over 43 days Meteostat and Open-Meteo agree on
83.6% of hours but with Cohen's kappa of only 0.495 — the raw figure is
flattered by both calling most hours dry. Part of every model's measured error
is therefore the yardstick's, and a ranking is only trustworthy if it survives
swapping one label for the other.
"""

import numpy as np
import pandas as pd
import pytest

import rainlib as rl
from daily_analysis import generate_ground_truth_agreement, kappa_label
from run_analysis import AnalysisConfig, ground_truth_agreement, score_against_alternative_truth


def series(values):
    idx = pd.date_range("2026-07-01", periods=len(values), freq="1h", tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


# ---------------------------------------------------------------------------
# cohens_kappa
# ---------------------------------------------------------------------------

def test_perfect_agreement():
    s = series([1, 0, 1, 0, 1, 0])
    result = rl.cohens_kappa(s, s)
    assert result["kappa"] == pytest.approx(1.0)
    assert result["observed_agreement"] == pytest.approx(1.0)


def test_total_disagreement_is_negative():
    a = series([1, 1, 0, 0])
    b = series([0, 0, 1, 1])
    assert rl.cohens_kappa(a, b)["kappa"] < 0


def test_rare_events_expose_the_gap_between_raw_agreement_and_kappa():
    """The reason kappa is reported: high raw agreement, no real skill.

    Both sources call 90 of 100 hours dry and their rain calls never coincide.
    Raw agreement is 80%, which sounds strong; kappa is negative.
    """
    a = series([1] * 10 + [0] * 90)
    b = series([0] * 10 + [1] * 10 + [0] * 80)

    result = rl.cohens_kappa(a, b)
    assert result["observed_agreement"] == pytest.approx(0.80)
    assert result["kappa"] < 0.1


def test_counts_are_reported_per_source():
    a = series([1, 1, 0, 0])
    b = series([1, 0, 0, 0])

    result = rl.cohens_kappa(a, b)
    assert (result["a_rain"], result["b_rain"], result["both_rain"]) == (2, 1, 1)


def test_unpaired_rows_are_dropped():
    a = series([1, 1, np.nan, 0])
    b = series([1, np.nan, 1, 0])
    assert rl.cohens_kappa(a, b)["n"] == 2


def test_kappa_undefined_when_a_source_never_varies():
    """Neither source ever reports rain — there is nothing to agree about."""
    result = rl.cohens_kappa(series([0, 0, 0, 0]), series([0, 0, 0, 0]))
    assert np.isnan(result["kappa"])
    assert result["observed_agreement"] == pytest.approx(1.0)


def test_empty_input():
    empty = pd.Series([], dtype=float)
    assert rl.cohens_kappa(empty, empty)["n"] == 0


def test_treats_any_positive_value_as_rain():
    """Sources arrive as 0/1 flags or as mm; both must label consistently."""
    flags = series([1, 0, 1, 0])
    millimetres = series([0.4, 0.0, 1.2, 0.0])
    assert rl.cohens_kappa(flags, millimetres)["kappa"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# ground_truth_agreement over a grid
# ---------------------------------------------------------------------------

def _grid(**cols):
    n = len(next(iter(cols.values())))
    idx = pd.date_range("2026-07-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({k: np.asarray(v, dtype=float) for k, v in cols.items()}, index=idx)


def test_all_source_pairs_are_compared():
    grid = _grid(om_precip=[0.0, 0.5, 0.0, 0.5],
                 ms_precip=[0.0, 0.5, 0.5, 0.0],
                 yx_is_rain=[0.0, 1.0, 0.0, 1.0])

    pairs = ground_truth_agreement(grid)["pairs"]
    assert set(pairs) == {"ms_vs_om", "ms_vs_yx", "om_vs_yx"}


def test_threshold_is_applied_to_precipitation():
    """Drizzle below the rain threshold is not rain."""
    grid = _grid(om_precip=[0.05, 0.5, 0.05, 0.5],
                 ms_precip=[0.0, 0.5, 0.0, 0.5])

    result = ground_truth_agreement(grid, threshold_mm=0.1)["pairs"]["ms_vs_om"]
    assert result["a_rain"] == 2
    assert result["kappa"] == pytest.approx(1.0)


def test_single_source_yields_no_pairs():
    assert ground_truth_agreement(_grid(om_precip=[0.0, 0.5]))["pairs"] == {}


def test_no_sources_at_all():
    result = ground_truth_agreement(pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC")))
    assert result == {"sources": [], "pairs": {}}


# ---------------------------------------------------------------------------
# Scoring against the alternative label
# ---------------------------------------------------------------------------

def test_alternative_scoring_is_empty_without_meteostat():
    grid = _grid(om_precip=[0.0, 0.5], model_original=[10.0, 90.0])
    assert score_against_alternative_truth(grid, AnalysisConfig()) == {}


def test_alternative_scoring_uses_the_meteostat_label():
    n = 8
    grid = _grid(
        ms_precip=[0.0, 0.0, 0.5, 0.5] * 2,
        model_original=[10.0, 10.0, 90.0, 90.0] * 2,
    )

    result = score_against_alternative_truth(grid, AnalysisConfig())
    assert result["original"]["precision"] == pytest.approx(1.0)
    assert result["original"]["recall"] == pytest.approx(1.0)


def test_alternative_scoring_ignores_unlabelled_hours():
    grid = _grid(
        ms_precip=[0.5, np.nan, 0.0, 0.5],
        model_original=[90.0, 90.0, 10.0, 90.0],
    )

    result = score_against_alternative_truth(grid, AnalysisConfig())
    assert result["original"]["tp"] == 2
    assert result["original"]["fp"] == 0


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kappa,expected", [
    (0.95, "almost perfect"), (0.7, "substantial"), (0.495, "moderate"),
    (0.3, "fair"), (0.05, "slight"), (-0.2, "poor"), (float("nan"), "undefined"),
])
def test_kappa_labels(kappa, expected):
    assert kappa_label(kappa) == expected


def _report(pairs=None, primary=None, alternative=None):
    return {
        "cross_check": {"ground_truth_agreement": {"sources": [], "pairs": pairs or {}}},
        "scoring": {"scores": primary or {}, "scores_vs_meteostat": alternative or {}},
    }


def test_render_flags_moderate_agreement():
    text = generate_ground_truth_agreement(_report(
        {"ms_vs_om": {"n": 1036, "observed_agreement": 0.836, "kappa": 0.495,
                      "a_rain": 171, "b_rain": 247, "both_rain": 124}}))

    assert "moderate" in text
    assert "the yardstick's, not the model's" in text


def test_render_does_not_flag_strong_agreement():
    text = generate_ground_truth_agreement(_report(
        {"ms_vs_om": {"n": 100, "observed_agreement": 0.95, "kappa": 0.90,
                      "a_rain": 20, "b_rain": 21, "both_rain": 19}}))

    assert "almost perfect" in text
    assert "yardstick" not in text


def test_render_confirms_a_stable_ranking():
    primary = {"combined": {"f1": 0.40}, "original": {"f1": 0.32}}
    alternative = {"combined": {"f1": 0.41}, "original": {"f1": 0.34}}

    text = generate_ground_truth_agreement(_report(primary=primary, alternative=alternative))
    assert "identical under both ground truths" in text


def test_render_flags_a_ranking_that_flips():
    primary = {"combined": {"f1": 0.40}, "original": {"f1": 0.32}}
    alternative = {"combined": {"f1": 0.30}, "original": {"f1": 0.45}}

    text = generate_ground_truth_agreement(_report(primary=primary, alternative=alternative))
    assert "Ranking changes" in text
    assert "unresolved" in text


def test_render_empty_without_data():
    assert generate_ground_truth_agreement({"cross_check": {}, "scoring": {}}) == ""
