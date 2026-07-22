"""Tests for temporal metrics with lead/lag windows."""

import pytest
import pandas as pd
import numpy as np
from rainlib_temporal import (
    confusion_with_windows,
    sweep_threshold_temporal,
    recommend_threshold_temporal,
)


def test_perfect_prediction_no_window():
    """Model predicts at exact same time as rain."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    pred = pd.Series([0, 0, 80, 80, 0, 0, 0, 0, 0, 0], index=index)
    truth = pd.Series([0, 0, 1, 1, 0, 0, 0, 0, 0, 0], index=index)
    
    result = confusion_with_windows(pred, truth, threshold=50, lead_hours=0, lag_hours=0)
    
    assert result["tp"] == 2  # Two rain hours predicted correctly
    assert result["fp"] == 0
    assert result["fn"] == 0
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0


def test_early_prediction_within_lead_window():
    """Model predicts 2 hours early, within 3-hour lead window."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    pred = pd.Series([0, 80, 80, 0, 0, 0, 0, 0, 0, 0], index=index)
    truth = pd.Series([0, 0, 0, 1, 1, 0, 0, 0, 0, 0], index=index)
    
    result = confusion_with_windows(pred, truth, threshold=50, lead_hours=3, lag_hours=1)
    
    # Predictions at hour 1 and 2 are within window of rain at hours 3-4
    assert result["tp"] == 2  # Both rain events matched
    assert result["fp"] == 0  # Early predictions count as TP, not FP
    assert result["fn"] == 0
    assert result["recall"] == 1.0


def test_too_early_prediction_outside_window():
    """Model predicts 4 hours early, outside 3-hour lead window."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    pred = pd.Series([80, 0, 0, 0, 0, 0, 0, 0, 0, 0], index=index)
    truth = pd.Series([0, 0, 0, 0, 1, 1, 0, 0, 0, 0], index=index)
    
    result = confusion_with_windows(pred, truth, threshold=50, lead_hours=3, lag_hours=1)
    
    # Prediction at hour 0 is >3 hours before rain at hours 4-5
    assert result["tp"] == 0
    assert result["fp"] == 1  # Too early = false positive
    assert result["fn"] == 2  # Missed both rain events
    assert result["recall"] == 0.0


def test_late_prediction_within_lag_window():
    """Model predicts 1 hour late, within 1-hour lag window."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    pred = pd.Series([0, 0, 0, 80, 0, 0, 0, 0, 0, 0], index=index)
    truth = pd.Series([0, 0, 1, 0, 0, 0, 0, 0, 0, 0], index=index)
    
    result = confusion_with_windows(pred, truth, threshold=50, lead_hours=3, lag_hours=1)
    
    # Prediction at hour 3 is 1 hour after rain at hour 2, within lag window
    assert result["tp"] == 1
    assert result["fp"] == 0
    assert result["fn"] == 0


def test_too_late_prediction_outside_lag_window():
    """Model predicts 2 hours late, outside 1-hour lag window."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    pred = pd.Series([0, 0, 0, 0, 80, 0, 0, 0, 0, 0], index=index)
    truth = pd.Series([0, 0, 1, 0, 0, 0, 0, 0, 0, 0], index=index)
    
    result = confusion_with_windows(pred, truth, threshold=50, lead_hours=3, lag_hours=1)
    
    # Prediction at hour 4 is 2 hours after rain at hour 2, outside lag window
    assert result["tp"] == 0
    assert result["fp"] == 1
    assert result["fn"] == 1


def test_multiple_predictions_one_event():
    """Multiple predictions in window count as single TP."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    pred = pd.Series([0, 80, 80, 80, 80, 0, 0, 0, 0, 0], index=index)
    truth = pd.Series([0, 0, 0, 1, 0, 0, 0, 0, 0, 0], index=index)
    
    result = confusion_with_windows(pred, truth, threshold=50, lead_hours=3, lag_hours=1)
    
    # All 4 predictions are within window of the single rain event
    assert result["tp"] == 1  # One rain event matched
    assert result["fp"] == 0  # All predictions matched to this event
    assert result["fn"] == 0


def test_no_predictions():
    """Model never predicts rain."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    pred = pd.Series([0, 0, 0, 0, 0, 0, 0, 0, 0, 0], index=index)
    truth = pd.Series([0, 0, 1, 1, 0, 0, 0, 0, 0, 0], index=index)
    
    result = confusion_with_windows(pred, truth, threshold=50, lead_hours=3, lag_hours=1)
    
    assert result["tp"] == 0
    assert result["fp"] == 0
    assert result["fn"] == 2
    assert result["recall"] == 0.0
    assert np.isnan(result["precision"])  # No predictions made


def test_no_rain():
    """No rain events."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    pred = pd.Series([80, 80, 0, 0, 0, 0, 0, 0, 0, 0], index=index)
    truth = pd.Series([0, 0, 0, 0, 0, 0, 0, 0, 0, 0], index=index)
    
    result = confusion_with_windows(pred, truth, threshold=50, lead_hours=3, lag_hours=1)
    
    assert result["tp"] == 0
    assert result["fp"] == 2  # Both predictions are false
    assert result["fn"] == 0
    assert np.isnan(result["recall"])  # No rain to recall
    assert result["precision"] == 0.0


def test_sweep_threshold_temporal():
    """Sweep across thresholds with temporal windows."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    pred = pd.Series([20, 50, 80, 90, 30, 10, 0, 0, 0, 0], index=index)
    truth = pd.Series([0, 0, 0, 1, 1, 0, 0, 0, 0, 0], index=index)
    
    sweep = sweep_threshold_temporal(
        pred, truth,
        lead_hours=3, lag_hours=1,
        thresholds=[30, 60, 90]
    )
    
    assert len(sweep) == 3
    assert 30 in sweep.index
    assert 60 in sweep.index
    assert 90 in sweep.index
    assert "precision" in sweep.columns
    assert "recall" in sweep.columns
    assert "f2" in sweep.columns


def test_recommend_threshold_temporal():
    """Test threshold recommendation with temporal metrics."""
    index = pd.date_range("2024-01-01", periods=20, freq="h")
    # Create pattern: predictions leading rain events
    pred = pd.Series([30, 60, 80, 50, 30, 0, 0, 40, 70, 90, 60, 30, 0, 0, 0, 0, 0, 0, 0, 0], index=index)
    truth = pd.Series([0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0], index=index)
    
    result = recommend_threshold_temporal(
        pred, truth,
        beta=2.0,  # Favor recall
        lead_hours=3,
        lag_hours=1,
        thresholds=range(20, 100, 10)
    )
    
    assert "best_threshold" in result
    assert "f_beta" in result
    assert "precision" in result
    assert "recall" in result
    assert not np.isnan(result["best_threshold"])
    assert 0 <= result["precision"] <= 1
    assert 0 <= result["recall"] <= 1


def test_f2_calculation():
    """Verify F2 score calculation (recall weighted 4x more)."""
    index = pd.date_range("2024-01-01", periods=10, freq="h")
    pred = pd.Series([80, 80, 80, 0, 0, 0, 0, 0, 0, 0], index=index)
    truth = pd.Series([0, 1, 1, 1, 0, 0, 0, 0, 0, 0], index=index)
    
    result = confusion_with_windows(pred, truth, threshold=50, lead_hours=3, lag_hours=1)
    
    # Manual calculation:
    # Pred at hour 0,1,2 with rain at 1,2,3
    # All 3 rain events are within lead window of the predictions
    # tp=3, fp=0, fn=0
    # precision = 1.0, recall = 1.0
    # F2 = 5 * 1.0 * 1.0 / (4 * 1.0 + 1.0) = 5/5 = 1.0
    assert result["tp"] == 3
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
    assert result["f2"] == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
