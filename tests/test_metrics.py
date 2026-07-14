"""
test_metrics.py — Unit tests for evaluation metrics

Tests confusion matrix, precision, recall, F1, and edge cases.
"""

import pytest
import numpy as np
import pandas as pd
from rainlib import confusion_at_threshold, fbeta_at_threshold


class TestConfusionMatrix:
    """Tests for confusion_at_threshold function."""
    
    def test_all_correct_predictions(self):
        """Perfect predictions: all TP and TN."""
        pred = pd.Series([100, 0, 100, 0])
        truth = pd.Series([1, 0, 1, 0])
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        assert result["tp"] == 2
        assert result["tn"] == 2
        assert result["fp"] == 0
        assert result["fn"] == 0
        assert result["precision"] == 1.0
        assert result["recall"] == 1.0
        assert result["f1"] == 1.0
    
    def test_all_wrong_predictions(self):
        """Worst case: all FP and FN."""
        pred = pd.Series([100, 100, 0, 0])
        truth = pd.Series([0, 0, 1, 1])
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        assert result["tp"] == 0
        assert result["tn"] == 0
        assert result["fp"] == 2
        assert result["fn"] == 2
        assert result["precision"] == 0.0
        assert result["recall"] == 0.0
        assert result["f1"] == 0.0
    
    def test_threshold_boundary(self):
        """Values exactly at threshold."""
        pred = pd.Series([50, 50, 49, 51])
        truth = pd.Series([1, 0, 1, 0])
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        # pred >= 50: indices 0,1,3 → predicted positive
        # pred < 50: index 2 → predicted negative
        assert result["tp"] == 1  # pred[0]=50, truth[0]=1
        assert result["fp"] == 2  # pred[1]=50, truth[1]=0 and pred[3]=51, truth[3]=0
        assert result["fn"] == 1  # pred[2]=49, truth[2]=1
        assert result["tn"] == 0


class TestPrecision:
    """Tests for precision calculation."""
    
    def test_perfect_precision(self):
        """All positive predictions are correct."""
        pred = pd.Series([100, 0, 100, 0])
        truth = pd.Series([1, 0, 1, 0])
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        assert result["precision"] == 1.0
    
    def test_zero_precision(self):
        """All positive predictions are wrong (all FP, no TP)."""
        pred = pd.Series([100, 100, 100, 100])
        truth = pd.Series([0, 0, 0, 0])
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        assert result["precision"] == 0.0
    
    def test_no_positive_predictions(self):
        """No positive predictions (TP + FP = 0) → precision = NaN."""
        pred = pd.Series([0, 0, 0, 0])
        truth = pd.Series([1, 1, 0, 0])
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        # No predicted positives, so precision is undefined (NaN)
        assert np.isnan(result["precision"])


class TestRecall:
    """Tests for recall calculation."""
    
    def test_perfect_recall(self):
        """All actual positives are caught."""
        pred = pd.Series([100, 100, 0, 0])
        truth = pd.Series([1, 1, 0, 0])
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        assert result["recall"] == 1.0
    
    def test_zero_recall(self):
        """All actual positives are missed (all FN, no TP)."""
        pred = pd.Series([0, 0, 0, 0])
        truth = pd.Series([1, 1, 1, 1])
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        assert result["recall"] == 0.0
    
    def test_no_actual_positives(self):
        """No rain events in ground truth (TP + FN = 0) → recall = NaN."""
        pred = pd.Series([100, 100, 0, 0])
        truth = pd.Series([0, 0, 0, 0])
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        # No actual positives, so recall is undefined (NaN)
        assert np.isnan(result["recall"])


class TestF1Score:
    """Tests for F1 score calculation."""
    
    def test_perfect_f1(self):
        """Perfect precision and recall → F1 = 1.0."""
        pred = pd.Series([100, 0, 100, 0])
        truth = pd.Series([1, 0, 1, 0])
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        assert result["f1"] == 1.0
    
    def test_f1_zero_when_precision_zero(self):
        """F1 calculation with actual values."""
        pred = pd.Series([100, 100, 100, 100])
        truth = pd.Series([0, 0, 0, 1])  # One actual positive
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        # Precision = 1/4 = 0.25, Recall = 1/1 = 1.0
        # F1 = 2 * (0.25 * 1.0) / (0.25 + 1.0) = 0.5 / 1.25 = 0.4
        assert result["precision"] == 0.25
        assert result["recall"] == 1.0
        assert abs(result["f1"] - 0.4) < 0.01
    
    def test_f1_zero_when_recall_zero(self):
        """F1 should be 0.0 when recall=0, precision>0."""
        pred = pd.Series([100, 0, 0, 0])
        truth = pd.Series([0, 1, 1, 1])  # Three actual positives, all missed
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        # Precision = 0/1 = 0.0, Recall = 0/3 = 0.0
        assert result["precision"] == 0.0
        assert result["recall"] == 0.0
        assert result["f1"] == 0.0
    
    def test_f1_balance(self):
        """F1 balances precision and recall."""
        # High precision, low recall
        pred = pd.Series([100, 0, 0, 0, 0])
        truth = pd.Series([1, 1, 1, 0, 0])
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        # Precision = 1/1 = 1.0, Recall = 1/3 = 0.333
        # F1 = 2 * 1.0 * 0.333 / (1.0 + 0.333) = 0.5
        assert result["precision"] == 1.0
        assert abs(result["recall"] - 0.333) < 0.01
        assert abs(result["f1"] - 0.5) < 0.01


class TestFBetaScore:
    """Tests for fbeta_at_threshold function."""
    
    def test_fbeta_equals_f1_when_beta_is_1(self):
        """F-beta with beta=1 should equal F1."""
        pred = pd.Series([80, 30, 60, 20])
        truth = pd.Series([1, 0, 1, 0])
        
        result_confusion = confusion_at_threshold(pred, truth, threshold=50)
        result_fbeta = fbeta_at_threshold(pred, truth, threshold=50, beta=1.0)
        
        assert abs(result_confusion["f1"] - result_fbeta) < 0.001
    
    def test_fbeta_favors_recall_when_beta_greater_1(self):
        """F2 (beta=2) weights recall higher than precision."""
        pred = pd.Series([100, 100, 0, 0, 0])
        truth = pd.Series([1, 0, 1, 1, 0])
        
        # Precision = 1/2 = 0.5, Recall = 1/3 = 0.333
        result_f1 = confusion_at_threshold(pred, truth, threshold=50)
        result_f2 = fbeta_at_threshold(pred, truth, threshold=50, beta=2.0)
        
        # F2 = (1 + 4) * (0.5 * 0.333) / (4 * 0.5 + 0.333)
        # F2 = 5 * 0.1665 / 2.333 = 0.357
        assert abs(result_f2 - 0.357) < 0.01


class TestEdgeCases:
    """Edge cases and boundary conditions."""
    
    def test_empty_input(self):
        """Empty series should return all zeros with NaN metrics."""
        pred = pd.Series([], dtype=float)
        truth = pd.Series([], dtype=int)
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        assert result["tp"] == 0
        assert result["tn"] == 0
        assert result["fp"] == 0
        assert result["fn"] == 0
        # Empty input means no predictions/ground truth → NaN
        assert np.isnan(result["precision"])
        assert np.isnan(result["recall"])
        assert np.isnan(result["f1"])
    
    def test_single_value(self):
        """Single data point."""
        pred = pd.Series([75])
        truth = pd.Series([1])
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        assert result["tp"] == 1
        assert result["precision"] == 1.0
        assert result["recall"] == 1.0
        assert result["f1"] == 1.0
    
    def test_all_below_threshold(self):
        """All predictions below threshold (all negatives)."""
        pred = pd.Series([10, 20, 30, 40])
        truth = pd.Series([0, 1, 0, 1])
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        assert result["tp"] == 0
        assert result["fp"] == 0
        assert result["fn"] == 2
        assert result["tn"] == 2
        # No positive predictions → precision undefined
        assert np.isnan(result["precision"])
        assert result["recall"] == 0.0
    
    def test_all_above_threshold(self):
        """All predictions above threshold (all positives)."""
        pred = pd.Series([60, 70, 80, 90])
        truth = pd.Series([1, 0, 1, 0])
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        assert result["tp"] == 2
        assert result["fp"] == 2
        assert result["fn"] == 0
        assert result["tn"] == 0
        assert result["precision"] == 0.5
        assert result["recall"] == 1.0
    
    def test_nan_values_dropped_by_default(self):
        """With drop_unknown=True (default), rows with NaN truth are dropped."""
        pred = pd.Series([100, np.nan, 0, 100])
        truth = pd.Series([1, 1, 0, np.nan])
        result = confusion_at_threshold(pred, truth, threshold=50)
        
        # Only rows 0 and 2 have non-NaN truth: (100,1) and (0,0)
        assert result["n"] == 2
        assert result["tp"] == 1
        assert result["tn"] == 1
        assert result["fp"] == 0
        assert result["fn"] == 0


class TestDropUnknown:
    """Tests for drop_unknown parameter in confusion_at_threshold."""

    def test_drop_unknown_true_excludes_nan_truth(self):
        """drop_unknown=True (default): NaN truth rows are excluded."""
        pred = pd.Series([100, 50, 100, 50])
        truth = pd.Series([1, np.nan, 0, np.nan])
        result = confusion_at_threshold(pred, truth, threshold=50, drop_unknown=True)

        assert result["n"] == 2  # only rows 0 and 2
        assert result["tp"] == 1
        assert result["fp"] == 1
        assert result["tn"] == 0
        assert result["fn"] == 0

    def test_drop_unknown_false_treats_nan_as_no_rain(self):
        """drop_unknown=False: NaN truth → 0 (no-rain)."""
        pred = pd.Series([100, 50, 100, 50])
        truth = pd.Series([1, np.nan, 0, np.nan])
        result = confusion_at_threshold(pred, truth, threshold=50, drop_unknown=False)

        assert result["n"] == 4  # all rows, NaN→0
        assert result["tp"] == 1  # row 0: pred≥50, truth=1
        # rows 1,3: pred≥50, truth→0 → FP; row 2: pred≥50, truth=0 → FP
        assert result["fp"] == 3
        assert result["tn"] == 0
        assert result["fn"] == 0

    def test_drop_unknown_false_nan_truth_does_not_inflate_recall(self):
        """NaN→0 only adds TN/FP, never TP — recall is unaffected."""
        pred = pd.Series([100, 10, 10])
        truth = pd.Series([1, np.nan, 0])

        result_true = confusion_at_threshold(pred, truth, threshold=50, drop_unknown=True)
        result_false = confusion_at_threshold(pred, truth, threshold=50, drop_unknown=False)

        # Recall should be identical (NaN→0 never creates new TP)
        assert result_true["recall"] == result_false["recall"]
        # But precision differs: drop_unknown=False inflates denominator with FP

    def test_drop_unknown_false_can_lower_precision(self):
        """drop_unknown=False can produce more FP → lower precision."""
        pred = pd.Series([100, 100, 10])
        truth = pd.Series([1, np.nan, 0])

        result_true = confusion_at_threshold(pred, truth, threshold=50, drop_unknown=True)
        result_false = confusion_at_threshold(pred, truth, threshold=50, drop_unknown=False)

        # drop_unknown=True: only 2 rows, TP=1, FP=0, precision=1.0
        # drop_unknown=False: 3 rows, TP=1, FP=1 (NaN→0), precision=0.5
        assert result_true["precision"] == 1.0
        assert result_false["precision"] == 0.5

    def test_drop_unknown_true_with_all_nan_truth(self):
        """drop_unknown=True with all-NaN truth → empty → NaN metrics."""
        pred = pd.Series([100, 50, 10])
        truth = pd.Series([np.nan, np.nan, np.nan])
        result = confusion_at_threshold(pred, truth, threshold=50, drop_unknown=True)

        assert result["n"] == 0
        assert result["tp"] == 0
        assert result["fp"] == 0
        assert result["tn"] == 0
        assert result["fn"] == 0
        assert np.isnan(result["precision"])
        assert np.isnan(result["recall"])
        assert np.isnan(result["f1"])

    def test_drop_unknown_false_with_all_nan_truth(self):
        """drop_unknown=False with all-NaN truth → all treated as no-rain."""
        pred = pd.Series([100, 50, 10])
        truth = pd.Series([np.nan, np.nan, np.nan])
        result = confusion_at_threshold(pred, truth, threshold=50, drop_unknown=False)

        assert result["n"] == 3
        assert result["tp"] == 0
        assert result["fp"] == 2  # 100 and 50 predicted rain, truth→0
        assert result["tn"] == 1  # 10 predicted no-rain, truth→0


class TestRealWorldScenarios:
    """Tests based on realistic model performance patterns."""
    
    def test_conservative_model(self):
        """Conservative model: high precision, low recall."""
        # Predicts rain only when very confident
        pred = pd.Series([90, 20, 30, 85, 40, 15, 95])
        truth = pd.Series([1, 1, 1, 1, 0, 0, 1])
        result = confusion_at_threshold(pred, truth, threshold=80)
        
        # Only 3 predictions above 80: indices 0, 3, 6
        # All three are actual rain → high precision
        # But missed 2 rain events → lower recall
        assert result["tp"] == 3
        assert result["fp"] == 0
        assert result["fn"] == 2
        assert result["precision"] == 1.0
        assert result["recall"] < 1.0
    
    def test_aggressive_model(self):
        """Aggressive model: high recall, low precision."""
        # Predicts rain often (low threshold)
        pred = pd.Series([60, 55, 45, 70, 30, 65, 50])
        truth = pd.Series([1, 0, 0, 1, 0, 0, 1])
        result = confusion_at_threshold(pred, truth, threshold=40)
        
        # Most predictions above 40 → catches all rain but many FP
        assert result["recall"] > 0.8  # High recall
        assert result["precision"] < 0.6  # Lower precision
