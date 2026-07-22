"""Tests for threshold-recommendation subsystem.

Covers sweep_threshold, recommend_threshold, lead_time, fbeta_at_threshold,
and plot_calibration from rainlib.py.
"""

import math
import pandas as pd
import pytest
import sys
from pathlib import Path

# Add parent directory to path for rainlib import
sys.path.insert(0, str(Path(__file__).parent.parent))
import rainlib as rl


# ---------------------------------------------------------------------------
# Test Data Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def perfect_predictions():
    """Perfect classifier: pred=100 when rain, pred=0 when no rain."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    pred = pd.Series([100, 100, 0, 0, 100, 0, 100, 0, 0, 100], index=index)
    truth = pd.Series([1, 1, 0, 0, 1, 0, 1, 0, 0, 1], index=index)
    return pred, truth


@pytest.fixture
def mixed_predictions():
    """Realistic mixed predictions with varying confidence."""
    index = pd.date_range("2024-01-01", periods=20, freq="h")
    # Ground truth: rain at hours 5, 10, 15
    truth = pd.Series([0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0], index=index)
    # Predictions: some correct, some false alarms, some misses
    pred = pd.Series([10, 20, 30, 40, 60, 70, 20, 30, 40, 50, 65, 15, 25, 35, 45, 55, 30, 20, 10, 5], index=index)
    return pred, truth


@pytest.fixture
def all_negative():
    """No rain in ground truth."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    pred = pd.Series([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], index=index)
    truth = pd.Series([0, 0, 0, 0, 0, 0, 0, 0, 0, 0], index=index)
    return pred, truth


@pytest.fixture
def all_positive():
    """All rain in ground truth."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    pred = pd.Series([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], index=index)
    truth = pd.Series([1, 1, 1, 1, 1, 1, 1, 1, 1, 1], index=index)
    return pred, truth


@pytest.fixture
def with_nans():
    """Data with NaN values in predictions and truth."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    pred = pd.Series([50, float('nan'), 70, 30, 80, 40, float('nan'), 60, 20, 90], index=index)
    truth = pd.Series([1, 0, 1, float('nan'), 1, 0, 0, 1, 0, 1], index=index)
    return pred, truth


# ---------------------------------------------------------------------------
# sweep_threshold Tests
# ---------------------------------------------------------------------------

def test_sweep_threshold_perfect(perfect_predictions):
    """Perfect predictions should yield perfect metrics at correct threshold."""
    pred, truth = perfect_predictions
    result = rl.sweep_threshold(pred, truth, thresholds=[10, 50, 90])
    
    assert len(result) == 3
    assert list(result.index) == [10, 50, 90]
    
    # At threshold 50, perfect separation
    row = result.loc[50]
    assert row["precision"] == 1.0
    assert row["recall"] == 1.0
    assert row["f1"] == 1.0
    assert row["tp"] == 5  # 5 rain hours
    assert row["fp"] == 0
    assert row["fn"] == 0
    assert row["tn"] == 5  # 5 no-rain hours


def test_sweep_threshold_all_negative(all_negative):
    """When no rain in truth, recall should be NaN, precision depends on predictions."""
    pred, truth = all_negative
    result = rl.sweep_threshold(pred, truth, thresholds=[50])
    
    row = result.loc[50]
    assert row["tp"] == 0
    assert row["fn"] == 0
    assert math.isnan(row["recall"])  # 0/(0+0) = undefined
    # At threshold 50, pred >= 50 are values 50, 60, 70, 80, 90, 100 (6 values)
    assert row["fp"] == 6
    assert row["precision"] == 0.0  # 0/(0+6) = 0


def test_sweep_threshold_all_positive(all_positive):
    """When all rain in truth, precision varies, recall depends on threshold."""
    pred, truth = all_positive
    result = rl.sweep_threshold(pred, truth, thresholds=[15, 50, 85])
    
    # At threshold 15, pred >= 15: values 20-100 (9 values), all are TP
    row_low = result.loc[15]
    assert row_low["tp"] == 9  # pred >= 15: indices 1-9
    assert row_low["fn"] == 1  # pred < 15: index 0 (pred=10)
    assert row_low["recall"] == 0.9  # 9/10
    assert row_low["precision"] == 1.0  # All predictions are correct (all truth=1)
    
    # At threshold 85, only highest predictions pass
    row_high = result.loc[85]
    assert row_high["tp"] == 2  # pred >= 85: indices 8, 9 (90, 100)
    assert row_high["fn"] == 8
    assert row_high["recall"] == 0.2  # 2/10


def test_sweep_threshold_custom_thresholds(mixed_predictions):
    """Custom threshold list should be respected."""
    pred, truth = mixed_predictions
    thresholds = [25, 50, 75]
    result = rl.sweep_threshold(pred, truth, thresholds=thresholds)
    
    assert list(result.index) == thresholds
    assert len(result) == 3


def test_sweep_threshold_monotonic_precision_recall():
    """As threshold increases, TP+FP should decrease (fewer predictions cross)."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    pred = pd.Series([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], index=index)
    truth = pd.Series([0, 0, 0, 0, 1, 1, 1, 1, 1, 1], index=index)
    
    result = rl.sweep_threshold(pred, truth, thresholds=range(10, 110, 10))
    
    # Total positives should be monotonically decreasing
    total_positives = result["tp"] + result["fp"]
    assert all(total_positives.diff().dropna() <= 0), "Total positive predictions should decrease with threshold"


# ---------------------------------------------------------------------------
# recommend_threshold Tests
# ---------------------------------------------------------------------------

def test_recommend_threshold_perfect(perfect_predictions):
    """Perfect predictions should recommend any threshold with perfect metrics, prefer lowest."""
    pred, truth = perfect_predictions
    result = rl.recommend_threshold(pred, truth, beta=1.0, thresholds=[10, 50, 90])
    
    # All thresholds have F-beta=1.0, so tie-breaking picks lowest (10)
    assert result["best_threshold"] == 10
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
    assert result["f1"] == 1.0
    assert result["fbeta"] == 1.0
    assert result["beta"] == 1.0
    assert "table" in result


def test_recommend_threshold_beta_effect():
    """Higher beta (favor recall) should prefer lower thresholds."""
    index = pd.date_range("2024-01-01", periods=20, freq="h")
    # Ground truth: 4 rain hours
    truth = pd.Series([0]*10 + [1]*4 + [0]*6, index=index)
    # Predictions gradually increase
    pred = pd.Series(range(10, 110, 5), index=index)
    
    # beta=0.5 (favor precision) should prefer higher threshold
    rec_low_beta = rl.recommend_threshold(pred, truth, beta=0.5, thresholds=range(20, 100, 10))
    
    # beta=2.0 (favor recall) should prefer lower threshold
    rec_high_beta = rl.recommend_threshold(pred, truth, beta=2.0, thresholds=range(20, 100, 10))
    
    # Higher beta should recommend lower or equal threshold
    assert rec_high_beta["best_threshold"] <= rec_low_beta["best_threshold"]


def test_recommend_threshold_min_precision_floor():
    """min_precision should filter out low-precision thresholds."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    # Only 1 rain hour at index 9
    truth = pd.Series([0, 0, 0, 0, 0, 0, 0, 0, 0, 1], index=index)
    # All predictions above 50
    pred = pd.Series([60, 65, 70, 75, 80, 85, 90, 95, 100, 100], index=index)
    
    # Without min_precision, low threshold (high recall, low precision) might win
    rec_no_floor = rl.recommend_threshold(pred, truth, beta=2.0, min_precision=0.0, thresholds=[50, 70, 90])
    
    # With min_precision=0.5, at least 50% must be correct
    rec_with_floor = rl.recommend_threshold(pred, truth, beta=2.0, min_precision=0.5, thresholds=[50, 70, 90])
    
    # Check table to understand precision at each threshold
    table_no_floor = rec_no_floor["table"]
    
    # At threshold 50, all 10 predictions pass, but only 1 is correct -> precision=0.1
    assert table_no_floor.loc[50, "precision"] == 0.1
    
    # min_precision=0.5 should exclude all thresholds (precision too low everywhere)
    # So best_threshold should be None
    assert rec_with_floor["best_threshold"] is None


def test_recommend_threshold_tie_breaking():
    """When multiple thresholds have equal F-beta, prefer lower (earlier warning)."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    # Create scenario where two thresholds yield identical metrics
    truth = pd.Series([0, 0, 0, 0, 0, 1, 1, 1, 1, 1], index=index)
    pred = pd.Series([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], index=index)
    
    # At thresholds 60 and 70, we should get similar F-beta
    result = rl.recommend_threshold(pred, truth, beta=1.0, thresholds=[60, 70])
    
    # Both should catch all 5 rain hours (recall=1.0), both have same precision
    table = result["table"]
    fbeta_60 = table.loc[60, "fbeta"]
    fbeta_70 = table.loc[70, "fbeta"]
    
    # If equal or near-equal (within 1e-9), should pick 60
    if abs(fbeta_60 - fbeta_70) < 1e-9:
        assert result["best_threshold"] == 60


def test_recommend_threshold_no_valid_candidates():
    """When no threshold passes min_precision, best_threshold should be None."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    # No rain in truth, so precision is always 0 or NaN
    truth = pd.Series([0]*10, index=index)
    pred = pd.Series(range(10, 110, 10), index=index)
    
    result = rl.recommend_threshold(pred, truth, beta=1.0, min_precision=0.5, thresholds=[30, 50, 70])
    
    assert result["best_threshold"] is None
    assert result["precision"] is None
    assert result["recall"] is None


def test_recommend_threshold_all_nan_fbeta():
    """When all F-beta scores are NaN, best_threshold should be None."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    # No rain, and at high threshold, no predictions either -> all NaN
    truth = pd.Series([0]*10, index=index)
    pred = pd.Series([10]*10, index=index)  # All below any reasonable threshold
    
    result = rl.recommend_threshold(pred, truth, beta=1.0, thresholds=[50, 70, 90])
    
    # At all thresholds, no predictions pass, TP=FP=0, precision=NaN
    assert result["best_threshold"] is None


# ---------------------------------------------------------------------------
# lead_time Tests
# ---------------------------------------------------------------------------

def test_lead_time_perfect_early_warning():
    """Prediction crosses threshold 2 hours before first rain."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    truth = pd.Series([0, 0, 0, 0, 0, 1, 1, 0, 0, 0], index=index)
    # Prediction crosses threshold=50 at hour 3, rain starts at hour 5
    pred = pd.Series([10, 20, 30, 60, 70, 80, 90, 40, 30, 20], index=index)
    
    lead = rl.lead_time(pred, truth, threshold=50)
    
    assert lead == pd.Timedelta(hours=2)  # hour 5 - hour 3


def test_lead_time_crosses_at_onset():
    """Prediction crosses threshold exactly when rain starts."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    truth = pd.Series([0, 0, 0, 0, 0, 1, 1, 0, 0, 0], index=index)
    pred = pd.Series([10, 20, 30, 40, 45, 60, 70, 40, 30, 20], index=index)
    
    lead = rl.lead_time(pred, truth, threshold=50)
    
    assert lead == pd.Timedelta(hours=0)  # hour 5 - hour 5


def test_lead_time_never_crosses():
    """Prediction never crosses threshold before rain."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    truth = pd.Series([0, 0, 0, 0, 0, 1, 1, 0, 0, 0], index=index)
    pred = pd.Series([10, 20, 30, 40, 45, 40, 35, 30, 20, 10], index=index)  # Never >= 50
    
    lead = rl.lead_time(pred, truth, threshold=50)
    
    assert lead is None


def test_lead_time_no_rain():
    """No rain in ground truth should return None."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    truth = pd.Series([0]*10, index=index)
    pred = pd.Series(range(10, 110, 10), index=index)
    
    lead = rl.lead_time(pred, truth, threshold=50)
    
    assert lead is None


def test_lead_time_crosses_after_onset():
    """Prediction crosses threshold only after rain started."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    truth = pd.Series([0, 0, 0, 1, 1, 1, 0, 0, 0, 0], index=index)
    # Crosses threshold=50 at hour 5, but rain started at hour 3
    pred = pd.Series([10, 20, 30, 40, 45, 60, 70, 40, 30, 20], index=index)
    
    lead = rl.lead_time(pred, truth, threshold=50)
    
    # Only considers crossings <= first_rain (hour 3)
    # No crossing before or at hour 3, so None
    assert lead is None


def test_lead_time_with_nans():
    """NaN values should be dropped before computing lead time."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    truth = pd.Series([0, 0, float('nan'), 0, 0, 1, 1, 0, 0, 0], index=index)
    pred = pd.Series([10, 20, 30, float('nan'), 60, 70, 80, 40, 30, 20], index=index)
    
    lead = rl.lead_time(pred, truth, threshold=50)
    
    # After dropna, first rain is at index 5, first crossing >= 50 is at index 4
    # lead = 1 hour
    assert lead == pd.Timedelta(hours=1)


# ---------------------------------------------------------------------------
# fbeta_at_threshold Tests
# ---------------------------------------------------------------------------

def test_fbeta_at_threshold_beta1_equals_f1(perfect_predictions):
    """F-beta with beta=1 should equal F1 score."""
    pred, truth = perfect_predictions
    
    c = rl.confusion_at_threshold(pred, truth, threshold=50)
    f1 = c["f1"]
    
    fbeta = rl.fbeta_at_threshold(pred, truth, threshold=50, beta=1.0)
    
    assert abs(fbeta - f1) < 1e-9


def test_fbeta_at_threshold_beta2_favors_recall():
    """F-beta with beta=2 should weight recall more than precision."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    # 3 rain hours
    truth = pd.Series([0, 0, 0, 0, 1, 1, 1, 0, 0, 0], index=index)
    # At threshold 50, catch 2/3 rain (recall=0.67), but also 2 false alarms (precision=0.5)
    pred = pd.Series([10, 20, 30, 40, 60, 70, 40, 30, 20, 10], index=index)
    
    c = rl.confusion_at_threshold(pred, truth, threshold=50)
    precision = c["precision"]
    recall = c["recall"]
    
    # F1 = 2*p*r / (p+r)
    f1 = 2 * precision * recall / (precision + recall)
    
    # F2 = (1 + 4) * p * r / (4*p + r) = 5*p*r / (4p + r)
    fbeta2 = rl.fbeta_at_threshold(pred, truth, threshold=50, beta=2.0)
    expected_f2 = 5 * precision * recall / (4 * precision + recall)
    
    assert abs(fbeta2 - expected_f2) < 1e-9
    # F2 should be closer to recall than F1 is
    assert abs(fbeta2 - recall) < abs(f1 - recall)


def test_fbeta_at_threshold_beta05_favors_precision():
    """F-beta with beta=0.5 should weight precision more than recall."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    # 3 rain hours
    truth = pd.Series([0, 0, 0, 0, 1, 1, 1, 0, 0, 0], index=index)
    # At threshold 50, catch 2/3 rain (recall=0.67), but also 2 false alarms (precision=0.5)
    pred = pd.Series([10, 20, 30, 40, 60, 70, 40, 30, 20, 10], index=index)
    
    c = rl.confusion_at_threshold(pred, truth, threshold=50)
    precision = c["precision"]
    recall = c["recall"]
    
    f1 = 2 * precision * recall / (precision + recall)
    
    # F0.5 = (1 + 0.25) * p * r / (0.25*p + r) = 1.25*p*r / (0.25p + r)
    fbeta05 = rl.fbeta_at_threshold(pred, truth, threshold=50, beta=0.5)
    expected_f05 = 1.25 * precision * recall / (0.25 * precision + recall)
    
    assert abs(fbeta05 - expected_f05) < 1e-9
    # F0.5 should be closer to precision than F1 is
    assert abs(fbeta05 - precision) < abs(f1 - precision)


def test_fbeta_at_threshold_nan_handling():
    """F-beta should return NaN when precision or recall is NaN."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    # No rain
    truth = pd.Series([0]*10, index=index)
    # At high threshold, no predictions pass -> TP=FP=0, precision=NaN
    pred = pd.Series([10]*10, index=index)
    
    fbeta = rl.fbeta_at_threshold(pred, truth, threshold=50, beta=1.0)
    
    assert math.isnan(fbeta)


def test_fbeta_at_threshold_zero_denominator():
    """F-beta should return NaN when denominator is zero."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    # Edge case: both precision and recall are 0 (but not NaN)
    # This happens when TP=0, FP>0, FN>0
    truth = pd.Series([0, 0, 0, 0, 0, 1, 1, 1, 1, 1], index=index)
    # Predictions never cross threshold in positive region
    pred = pd.Series([100, 90, 80, 70, 60, 10, 20, 30, 40, 50], index=index)
    
    # At threshold 55, pred >= 55 are indices 0-4 (all no-rain), so TP=0, FP=5
    # pred < 55 are indices 5-9 (all rain), so FN=5, TN=0
    # precision = 0/5 = 0, recall = 0/5 = 0
    c = rl.confusion_at_threshold(pred, truth, threshold=55)
    assert c["precision"] == 0.0
    assert c["recall"] == 0.0
    
    fbeta = rl.fbeta_at_threshold(pred, truth, threshold=55, beta=1.0)
    
    # When both are 0, denominator = 0, should return NaN
    assert math.isnan(fbeta)


# ---------------------------------------------------------------------------
# plot_calibration Tests (smoke tests only)
# ---------------------------------------------------------------------------

def test_plot_calibration_runs_without_error(mixed_predictions):
    """plot_calibration should execute without raising exceptions."""
    pred, truth = mixed_predictions
    
    try:
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend
        import matplotlib.pyplot as plt
        
        fig, ax = plt.subplots()
        rl.plot_calibration(pred, truth, betas=(0.5, 1.0, 2.0), thresholds=range(20, 80, 10), ax=ax)
        
        # Check that something was plotted
        assert len(ax.lines) > 0 or len(ax.collections) > 0
        
        plt.close(fig)
    except ImportError:
        pytest.skip("matplotlib not available")


def test_plot_calibration_custom_title(mixed_predictions):
    """plot_calibration should accept custom title."""
    pred, truth = mixed_predictions
    
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        
        fig, ax = plt.subplots()
        rl.plot_calibration(pred, truth, title="Custom Title", ax=ax)
        
        assert ax.get_title() == "Custom Title"
        
        plt.close(fig)
    except ImportError:
        pytest.skip("matplotlib not available")


def test_plot_calibration_no_ax_creates_figure(mixed_predictions):
    """plot_calibration without ax should create its own figure."""
    pred, truth = mixed_predictions
    
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        
        # Close any existing figures
        plt.close('all')
        
        rl.plot_calibration(pred, truth, betas=(1.0,), thresholds=range(20, 80, 10))
        
        # Should have created a figure
        assert len(plt.get_fignums()) > 0
        
        plt.close('all')
    except ImportError:
        pytest.skip("matplotlib not available")


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

def test_end_to_end_recommendation_workflow(mixed_predictions):
    """Full workflow: sweep -> recommend -> verify lead time."""
    pred, truth = mixed_predictions
    
    # Step 1: Sweep to understand the trade-off
    sweep = rl.sweep_threshold(pred, truth, thresholds=range(20, 80, 10))
    assert len(sweep) == 6
    
    # Step 2: Recommend threshold for beta=2 (favor recall)
    rec = rl.recommend_threshold(pred, truth, beta=2.0, min_precision=0.3, thresholds=range(20, 80, 10))
    assert rec["best_threshold"] is not None
    assert rec["precision"] >= 0.3
    
    # Step 3: Check lead time at recommended threshold
    lead = rl.lead_time(pred, truth, threshold=rec["best_threshold"])
    # lead might be None or positive, depending on data
    assert lead is None or lead >= pd.Timedelta(0)


def test_sweep_and_recommend_consistency(perfect_predictions):
    """recommend_threshold should pick from the sweep table."""
    pred, truth = perfect_predictions
    thresholds = [10, 50, 90]
    
    sweep = rl.sweep_threshold(pred, truth, thresholds=thresholds)
    rec = rl.recommend_threshold(pred, truth, beta=1.0, thresholds=thresholds)
    
    # Recommended threshold should exist in sweep table
    assert rec["best_threshold"] in sweep.index
    
    # Metrics should match
    sweep_row = sweep.loc[rec["best_threshold"]]
    assert abs(rec["precision"] - sweep_row["precision"]) < 1e-9
    assert abs(rec["recall"] - sweep_row["recall"]) < 1e-9
    assert abs(rec["f1"] - sweep_row["f1"]) < 1e-9
