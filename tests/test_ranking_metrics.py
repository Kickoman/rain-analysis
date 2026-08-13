"""
Tests for the threshold-free ranking metrics.

F1 at a fixed 50% threshold was the only headline metric, and it hid models that
cannot rank at all: `ha_live` posted F1 0.313 while sitting at ROC AUC 0.579, and
`trend_dominant` posted F1 0.234 at AUC 0.505 — a coin flip. AUC and average
precision are threshold-free, so no cutoff can rescue a model that does not
separate the classes.

Both are implemented in rainlib rather than pulled from scikit-learn, so these
tests pin the values against hand-computed cases.
"""

import numpy as np
import pandas as pd
import pytest

import rainlib as rl


def s(values):
    return pd.Series(values, dtype=float)


# ---------------------------------------------------------------------------
# roc_auc
# ---------------------------------------------------------------------------

def test_perfect_ranking():
    assert rl.roc_auc(s([1, 2, 3, 4]), s([0, 0, 1, 1])) == pytest.approx(1.0)


def test_inverted_ranking():
    assert rl.roc_auc(s([4, 3, 2, 1]), s([0, 0, 1, 1])) == pytest.approx(0.0)


def test_constant_score_is_chance():
    """A model that outputs the same value for everything ranks nothing."""
    assert rl.roc_auc(s([50, 50, 50, 50]), s([0, 1, 0, 1])) == pytest.approx(0.5)


def test_auc_is_the_probability_of_correct_ordering():
    """One positive above two of three negatives = 2/3."""
    assert rl.roc_auc(s([2.0, 1.0, 3.0, 1.5]), s([1, 0, 0, 0])) == pytest.approx(2 / 3)


def test_ties_get_half_credit():
    """A tie between one positive and one negative is half a correct ordering."""
    assert rl.roc_auc(s([1.0, 1.0]), s([1, 0])) == pytest.approx(0.5)


def test_auc_ignores_threshold_scale():
    """Rescaling scores cannot change a ranking metric."""
    truth = s([0, 1, 0, 1, 1])
    pred = s([10, 80, 30, 60, 90])
    assert rl.roc_auc(pred, truth) == pytest.approx(rl.roc_auc(pred / 100, truth))


def test_auc_needs_both_classes():
    assert np.isnan(rl.roc_auc(s([1, 2, 3]), s([0, 0, 0])))
    assert np.isnan(rl.roc_auc(s([1, 2, 3]), s([1, 1, 1])))


def test_auc_drops_unlabelled_hours():
    """Unknown ground truth must not be scored as dry."""
    assert rl.roc_auc(s([1, np.nan, 3]), s([0, 1, 1])) == pytest.approx(1.0)


def test_auc_empty():
    assert np.isnan(rl.roc_auc(pd.Series([], dtype=float), pd.Series([], dtype=float)))


# ---------------------------------------------------------------------------
# average_precision
# ---------------------------------------------------------------------------

def test_average_precision_perfect():
    assert rl.average_precision(s([1, 2, 3, 4]), s([0, 0, 1, 1])) == pytest.approx(1.0)


def test_average_precision_floor_is_the_base_rate():
    """With no ranking ability, AP collapses to the share of positives."""
    truth = s([1, 0, 0, 0, 1, 0, 0, 0, 0, 0])
    assert rl.average_precision(s([5.0] * 10), truth) == pytest.approx(0.2)


def test_average_precision_rewards_positives_ranked_first():
    truth = s([1, 1, 0, 0])
    assert rl.average_precision(s([4, 3, 2, 1]), truth) == pytest.approx(1.0)

    # Both positives ranked last: precision@3 = 1/3, precision@4 = 2/4,
    # averaged over the two positives.
    assert rl.average_precision(s([2, 1, 4, 3]), truth) == pytest.approx((1 / 3 + 1 / 2) / 2)


def test_average_precision_needs_a_positive():
    assert np.isnan(rl.average_precision(s([1, 2, 3]), s([0, 0, 0])))


def test_average_precision_handles_ties_as_one_block():
    """Tied scores share a precision — no threshold can separate them."""
    result = rl.average_precision(s([1, 1, 1, 1]), s([1, 0, 1, 0]))
    assert result == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# The property that motivated all of this
# ---------------------------------------------------------------------------

def test_f1_can_look_respectable_while_auc_says_chance():
    """The failure mode these metrics exist to expose.

    A model whose output is unrelated to the truth but happens to sit near the
    decision threshold posts a non-trivial F1 while ranking at chance.
    """
    rng = np.random.default_rng(0)
    n = 400
    truth = pd.Series((rng.random(n) < 0.3).astype(float))
    pred = pd.Series(rng.normal(50, 5, n))   # no relationship to truth at all

    f1 = rl.confusion_at_threshold(pred, truth, 50.0)["f1"]
    auc = rl.roc_auc(pred, truth)

    assert f1 > 0.2                       # looks like it is doing something
    assert auc == pytest.approx(0.5, abs=0.06)   # it is not
