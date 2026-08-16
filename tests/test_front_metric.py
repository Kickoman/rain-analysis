"""Tests for the rain-front (onset-only) target and its scoring.

The motivating failure: the warning target counts every in-rain hour as a
positive, so persistence — which cannot predict a single onset from a dry
hour — outranked every model (warning AUC 0.712 vs front AUC 0.485 over
2026-07-01→08-14). The front target must be immune to that: recognising
ongoing rain earns nothing.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "analysis"))

import rainlib as rl
from run_analysis import AnalysisConfig, score_front_target


def series(values, start="2026-08-01"):
    idx = pd.date_range(start, periods=len(values), freq="1h", tz="UTC")
    return pd.Series([np.nan if v is None else float(v) for v in values], index=idx)


# ---------------------------------------------------------------------------
# detect_onsets
# ---------------------------------------------------------------------------

def test_onset_requires_dry_run_before():
    labels = series([0, 0, 0, 1, 1, 0, 1])
    onsets = rl.detect_onsets(labels, dry_hours=3)
    assert list(onsets) == [0, 0, 0, 1, 0, 0, 0]
    # hour 6 rains again after only one dry hour: same event, not a new front


def test_unknown_history_does_not_manufacture_an_onset():
    labels = series([0, None, 0, 1])
    assert rl.detect_onsets(labels, dry_hours=3).sum() == 0


def test_dry_hours_zero_degenerates_to_rain_label():
    labels = series([0, 1, 1])
    assert list(rl.detect_onsets(labels, dry_hours=0)) == [0, 1, 1]


# ---------------------------------------------------------------------------
# label_front_within
# ---------------------------------------------------------------------------

def test_front_label_marks_only_the_dry_approach():
    labels = series([0, 0, 0, 0, 1, 1, 0])
    front = rl.label_front_within(labels, hours=3, dry_hours=3)
    # hours 1-3 are within 3h of the onset at hour 4
    assert front.iloc[1] == 1.0 and front.iloc[2] == 1.0 and front.iloc[3] == 1.0
    # in-rain hours are not scored at all
    assert np.isnan(front.iloc[4]) and np.isnan(front.iloc[5])


def test_front_label_is_nan_when_horizon_is_unknown():
    labels = series([0, 0, 0, 0, 0])
    front = rl.label_front_within(labels, hours=3, dry_hours=3)
    # the last hours cannot see 3h ahead — unknown, not "no front"
    assert np.isnan(front.iloc[-1]) and np.isnan(front.iloc[-2])


def test_continuing_rain_is_not_a_front():
    # rain at hour 4 continues at 5; a dry hour before 4 sees a front,
    # but nothing after the rain begins is scored
    labels = series([0, 0, 0, 0, 1, 1, 1, 1])
    front = rl.label_front_within(labels, hours=3, dry_hours=3)
    assert front.iloc[3] == 1.0
    assert front.iloc[4:].isna().all()


# ---------------------------------------------------------------------------
# score_front_target: persistence must not profit
# ---------------------------------------------------------------------------

def _grid_with_one_front():
    """12 dry hours, then 4 rain, then dry tail; a model that alerts before
    the onset and persistence which by construction cannot."""
    labels = series([0] * 12 + [1] * 4 + [0] * 8)
    grid = pd.DataFrame(index=labels.index)
    grid["rain_truth"] = labels
    grid["rain_truth_window"] = rl.label_rain_within(labels, 3)
    grid["front_truth"] = rl.label_front_within(labels, 3, 3)
    # an anticipating model: high only in the 3 hours before the onset
    anticipate = pd.Series(0.0, index=labels.index)
    anticipate.iloc[9:12] = 90.0
    grid["model_original"] = anticipate
    return grid


def test_anticipating_model_beats_persistence_on_fronts(monkeypatch):
    import run_analysis
    monkeypatch.setattr(run_analysis, "MODELS", {"original": None})

    grid = _grid_with_one_front()
    config = AnalysisConfig()
    result = score_front_target(grid, config)

    assert result["n_onsets"] == 1
    model = result["scores"]["original"]
    persistence = result["scores"]["persistence"]

    assert model["events"] is not None
    assert model["events"]["onsets_caught"] == 1
    assert model["events"]["precision"] == 1.0

    # persistence is 100 only right after rain — never on the dry approach
    assert persistence["events"] is None or persistence["events"]["onsets_caught"] == 0
    assert result["best_model"] == "original"


def test_front_scoring_skips_windows_without_both_classes(monkeypatch):
    import run_analysis
    monkeypatch.setattr(run_analysis, "MODELS", {"original": None})

    labels = series([0] * 10)
    grid = pd.DataFrame(index=labels.index)
    grid["rain_truth"] = labels
    grid["front_truth"] = rl.label_front_within(labels, 3, 3)
    grid["model_original"] = pd.Series(0.0, index=labels.index)

    assert score_front_target(grid, AnalysisConfig()) == {}
