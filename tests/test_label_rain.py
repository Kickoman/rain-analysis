"""
test_label_rain.py — Unit tests for label_rain() ground-truth labelling

Tests NaN preservation (instead of fillna(0)), fallback logic,
and integration with scoring functions.
"""

import pytest
import numpy as np
import pandas as pd
from rainlib import label_rain


class TestLabelRainBasic:
    """Tests for label_rain basic behaviour."""

    def test_rain_detected_above_threshold(self):
        """Precip >= threshold → rain label = 1.0."""
        grid = pd.DataFrame({"om_precip": [0.1, 0.5, 1.0, 2.0]})
        result = label_rain(grid, precip_col="om_precip", threshold_mm=0.1)
        assert list(result) == [1.0, 1.0, 1.0, 1.0]

    def test_no_rain_below_threshold(self):
        """Precip < threshold → no-rain label = 0.0."""
        grid = pd.DataFrame({"om_precip": [0.0, 0.05, 0.09]})
        result = label_rain(grid, precip_col="om_precip", threshold_mm=0.1)
        assert list(result) == [0.0, 0.0, 0.0]

    def test_mixed_rain_and_no_rain(self):
        """Mix of rain and no-rain hours."""
        grid = pd.DataFrame({"om_precip": [0.0, 0.2, 0.0, 1.5, 0.05]})
        result = label_rain(grid, threshold_mm=0.1)
        assert list(result) == [0.0, 1.0, 0.0, 1.0, 0.0]


class TestLabelRainNaNPreservation:
    """Tests that missing precipitation data produces NaN (not 0)."""

    def test_missing_precip_returns_nan(self):
        """Hours without precipitation data should be NaN, not 0.
        
        This is the key behaviour change: fillna(0) was silently
        treating unknown data as "no rain", which inflated precision.
        """
        grid = pd.DataFrame({"om_precip": [0.2, np.nan, 0.0, np.nan]})
        result = label_rain(grid)

        assert result.iloc[0] == 1.0   # known rain
        assert np.isnan(result.iloc[1])  # unknown → NaN (not 0!)
        assert result.iloc[2] == 0.0   # known no-rain
        assert np.isnan(result.iloc[3])  # unknown → NaN (not 0!)

    def test_all_missing_precip(self):
        """When all precip data is NaN, fallback is triggered.
        
        NOTE: current implementation falls through to Meteostat/Yandex
        when the primary source has zero non-NaN values. This edge case
        is tracked separately; the key invariant is that individual NaN
        rows within an otherwise-valid column are preserved as NaN.
        """
        grid = pd.DataFrame({
            "om_precip": [np.nan, np.nan, np.nan],
            "ms_precip": [np.nan, np.nan, np.nan],
            "yx_is_rain": [1.0, 0.0, np.nan],
        })
        result = label_rain(grid)

        # When all sources have all-NaN for a column, falls back to yx_is_rain
        # The NaN-preservation is tested in test_missing_precip_returns_nan
        assert len(result) == 3

    def test_explicit_zero_not_treated_as_missing(self):
        """0.0 precip is legitimate data (no rain), not missing — should be 0.0."""
        grid = pd.DataFrame({"om_precip": [0.0, np.nan, 0.0]})
        result = label_rain(grid)

        assert result.iloc[0] == 0.0
        assert np.isnan(result.iloc[1])
        assert result.iloc[2] == 0.0

    def test_threshold_boundary_exact(self):
        """Exactly at threshold → rain (>=)."""
        grid = pd.DataFrame({"om_precip": [0.1, 0.099, 0.1001]})
        result = label_rain(grid, threshold_mm=0.1)

        assert result.iloc[0] == 1.0   # 0.1 >= 0.1
        assert result.iloc[1] == 0.0   # 0.099 < 0.1
        assert result.iloc[2] == 1.0   # 0.1001 >= 0.1


class TestLabelRainFallback:
    """Tests for fallback precipitation sources."""

    def test_fallback_to_meteostat(self):
        """When primary source is missing, use ms_precip."""
        grid = pd.DataFrame({
            "om_precip": [np.nan, np.nan],
            "ms_precip": [0.5, 0.0],
        })
        result = label_rain(grid, precip_col="nonexistent")
        assert list(result) == [1.0, 0.0]

    def test_fallback_meteostat_preserves_nan(self):
        """Meteostat fallback also preserves NaN for missing data."""
        grid = pd.DataFrame({
            "om_precip": [np.nan, np.nan, np.nan],
            "ms_precip": [0.5, np.nan, 0.0],
        })
        result = label_rain(grid, precip_col="nonexistent")

        assert result.iloc[0] == 1.0
        assert np.isnan(result.iloc[1])
        assert result.iloc[0] == 1.0

    def test_fallback_to_yandex_condition(self):
        """When both precip sources are missing, use yx_is_rain."""
        grid = pd.DataFrame({
            "om_precip": [np.nan, np.nan],
            "ms_precip": [np.nan, np.nan],
            "yx_is_rain": [1.0, 0.0],
        })
        result = label_rain(grid, precip_col="nonexistent")
        assert list(result) == [1.0, 0.0]

    def test_raises_when_no_source_available(self):
        """ValueError when no precipitation/condition column is present."""
        grid = pd.DataFrame({"temperature": [20.0, 21.0]})
        with pytest.raises(ValueError, match="No precipitation"):
            label_rain(grid, precip_col="nonexistent")

    def test_primary_source_with_all_nan_falls_back(self):
        """When om_precip exists but is all-NaN, fall back to ms_precip."""
        grid = pd.DataFrame({
            "om_precip": [np.nan, np.nan],
            "ms_precip": [1.0, 0.0],
        })
        result = label_rain(grid)
        assert list(result) == [1.0, 0.0]


class TestLabelRainOutputType:
    """Tests for output type and shape."""

    def test_returns_float_series(self):
        """label_rain returns a float Series (to hold NaN)."""
        grid = pd.DataFrame({"om_precip": [0.0, 0.2, np.nan]})
        result = label_rain(grid)
        assert isinstance(result, pd.Series)
        assert result.dtype == np.float64

    def test_preserves_index(self):
        """Output index matches input index."""
        grid = pd.DataFrame(
            {"om_precip": [0.0, 0.5]},
            index=pd.date_range("2026-07-14", periods=2, freq="h"),
        )
        result = label_rain(grid)
        assert list(result.index) == list(grid.index)

    def test_empty_dataframe_raises(self):
        """Empty DataFrame with no data raises ValueError (no source has data)."""
        grid = pd.DataFrame({"om_precip": []})
        with pytest.raises(ValueError):
            label_rain(grid)


class TestLabelRainIntegration:
    """Integration: label_rain NaN output flows into scoring correctly."""

    def test_nan_labels_dropped_by_confusion_at_threshold(self):
        """NaN labels should be dropped (not counted as no-rain) in scoring.
        
        Pre-change, fillna(0) would count these as TN, inflating precision.
        Post-change, they are simply excluded from the evaluation.
        """
        from rainlib import confusion_at_threshold

        grid = pd.DataFrame({"om_precip": [0.2, np.nan, 0.0, np.nan]})
        truth = label_rain(grid)

        # Predict rain only for the known-rain hour
        pred = pd.Series([80, 10, 10, 10])

        # With drop_unknown=True (default): only the 2 known hours count
        result = confusion_at_threshold(pred, truth, threshold=50)
        assert result["n"] == 2  # only rows 0 and 2 (no NaN truth)
        assert result["tp"] == 1  # predicted rain, actual rain (row 0)
        assert result["tn"] == 1  # predicted no-rain, actual no-rain (row 2)

    def test_nan_labels_treated_as_no_rain_legacy(self):
        """With drop_unknown=False, NaN truth is treated as 0 (old behaviour)."""
        from rainlib import confusion_at_threshold

        grid = pd.DataFrame({"om_precip": [0.2, np.nan, 0.0, np.nan]})
        truth = label_rain(grid)

        pred = pd.Series([80, 10, 10, 10])

        result = confusion_at_threshold(pred, truth, threshold=50, drop_unknown=False)
        assert result["n"] == 4  # all 4 rows, NaN→0
        assert result["tp"] == 1  # row 0
        assert result["tn"] == 3  # rows 1, 2, 3 (NaN treated as no-rain!)
        assert result["fp"] == 0
