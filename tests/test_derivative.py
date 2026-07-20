"""
test_derivative.py — Unit tests for derivative() function

Tests the derivative helper which computes least-squares slope
over a trailing time window with optional gap rejection.
"""

import pytest
import numpy as np
import pandas as pd
from rainlib import derivative


class TestDerivativeBasic:
    """Basic derivative calculations."""
    
    def test_linear_increase(self):
        """Derivative of linear increasing data should be constant."""
        # Create hourly data increasing by 1°C per hour
        times = pd.date_range("2024-01-01 00:00", periods=10, freq="1h", tz="UTC")
        values = pd.Series(range(10), index=times, dtype=float)
        
        deriv = derivative(values, window="3h", min_periods=2)
        
        # After initial window buildup, should stabilize at ~1.0 °C/h
        stable = deriv.iloc[3:]  # Skip initial points
        assert stable.notna().all()
        assert np.allclose(stable, 1.0, atol=0.1)
    
    def test_linear_decrease(self):
        """Derivative of linear decreasing data should be negative."""
        times = pd.date_range("2024-01-01 00:00", periods=10, freq="1h", tz="UTC")
        values = pd.Series([10 - i for i in range(10)], index=times, dtype=float)
        
        deriv = derivative(values, window="3h", min_periods=2)
        
        stable = deriv.iloc[3:]
        assert stable.notna().all()
        assert np.allclose(stable, -1.0, atol=0.1)
    
    def test_constant_series(self):
        """Derivative of constant series should be zero."""
        times = pd.date_range("2024-01-01 00:00", periods=10, freq="1h", tz="UTC")
        values = pd.Series([20.0] * 10, index=times)
        
        deriv = derivative(values, window="3h", min_periods=2)
        
        # Derivatives should be zero (or very close) after initial point
        assert deriv.iloc[1:].notna().all()
        assert np.allclose(deriv.iloc[1:], 0.0, atol=0.01)
    
    def test_empty_series(self):
        """Empty series returns empty result."""
        empty = pd.Series([], dtype=float)
        deriv = derivative(empty, window="1h")
        assert len(deriv) == 0
    
    def test_all_nan_series(self):
        """Series with all NaN returns all NaN."""
        times = pd.date_range("2024-01-01 00:00", periods=5, freq="1h", tz="UTC")
        values = pd.Series([np.nan] * 5, index=times)
        
        deriv = derivative(values, window="3h")
        assert deriv.isna().all()


class TestDerivativeMinPeriods:
    """Tests for min_periods parameter."""
    
    def test_min_periods_requirement(self):
        """Points with fewer samples than min_periods are NaN."""
        times = pd.date_range("2024-01-01 00:00", periods=5, freq="1h", tz="UTC")
        values = pd.Series(range(5), index=times, dtype=float)
        
        # Require at least 4 points in 4h window
        deriv = derivative(values, window="4h", min_periods=4)
        
        # First points won't have 4 samples in 4h window
        assert deriv.iloc[0:3].isna().all()
        # Last points (indices 3 and 4) should have 4 samples in window
        assert deriv.iloc[3:].notna().any()
    
    def test_min_periods_default(self):
        """Default min_periods=2 allows derivative with just 2 points."""
        times = pd.date_range("2024-01-01 00:00", periods=3, freq="1h", tz="UTC")
        values = pd.Series([0.0, 1.0, 2.0], index=times)
        
        deriv = derivative(values, window="2h", min_periods=2)
        
        # Should have values starting from second point
        assert deriv.iloc[1:].notna().all()


class TestDerivativeIrregularTimestamps:
    """Tests for handling irregular timestamps."""
    
    def test_irregular_spacing(self):
        """Derivative handles irregular time spacing correctly."""
        times = pd.DatetimeIndex([
            "2024-01-01 00:00",
            "2024-01-01 00:30",  # 30 min gap
            "2024-01-01 01:00",  # 30 min gap
            "2024-01-01 02:00",  # 60 min gap
            "2024-01-01 02:15",  # 15 min gap
        ], tz="UTC")
        # Values increase by 1 per hour
        values = pd.Series([0.0, 0.5, 1.0, 2.0, 2.25], index=times)
        
        deriv = derivative(values, window="2h", min_periods=2)
        
        # Should compute slopes correctly despite irregular spacing
        assert deriv.notna().sum() >= 3
        # Slope should be approximately 1.0 °C/h
        stable = deriv.dropna()
        assert (stable >= 0.8).all() and (stable <= 1.2).all()
    
    def test_respects_actual_time_deltas(self):
        """Derivative uses actual time deltas, not sample count."""
        # Two scenarios: same number of points, different time spans
        
        # Scenario 1: 3 points over 2 hours (slower change)
        times1 = pd.DatetimeIndex([
            "2024-01-01 00:00",
            "2024-01-01 01:00",
            "2024-01-01 02:00",
        ], tz="UTC")
        values1 = pd.Series([0.0, 1.0, 2.0], index=times1)
        deriv1 = derivative(values1, window="3h", min_periods=2)
        
        # Scenario 2: 3 points over 30 minutes (faster change)
        times2 = pd.DatetimeIndex([
            "2024-01-01 00:00",
            "2024-01-01 00:15",
            "2024-01-01 00:30",
        ], tz="UTC")
        values2 = pd.Series([0.0, 1.0, 2.0], index=times2)
        deriv2 = derivative(values2, window="1h", min_periods=2)
        
        # Both have same value change (0→2), but different time spans
        # Scenario 1: 2°C over 2h = 1.0 °C/h
        # Scenario 2: 2°C over 0.5h = 4.0 °C/h
        assert np.allclose(deriv1.iloc[-1], 1.0, atol=0.1)
        assert np.allclose(deriv2.iloc[-1], 4.0, atol=0.2)


class TestDerivativeMaxGap:
    """Tests for max_gap parameter to reject windows with large gaps."""
    
    def test_max_gap_rejects_gapped_windows(self):
        """Windows with gaps larger than max_gap are rejected."""
        times = pd.DatetimeIndex([
            "2024-01-01 00:00",
            "2024-01-01 00:30",
            "2024-01-01 03:00",  # 2.5 hour gap (sensor downtime)
            "2024-01-01 03:30",
            "2024-01-01 04:00",
        ], tz="UTC")
        values = pd.Series([0.0, 0.5, 3.0, 3.5, 4.0], index=times)
        
        # Reject windows with gaps > 1 hour
        deriv = derivative(values, window="4h", min_periods=2, max_gap="1h")
        
        # Point at 03:00 has a large gap before it - should be NaN
        assert deriv.loc["2024-01-01 03:00"] is np.nan or pd.isna(deriv.loc["2024-01-01 03:00"])
        
        # Points after the gap (once window moves past it) should be valid
        assert deriv.loc["2024-01-01 04:00"] is not np.nan
    
    def test_max_gap_none_allows_all(self):
        """max_gap=None allows any gap size."""
        times = pd.DatetimeIndex([
            "2024-01-01 00:00",
            "2024-01-01 00:30",
            "2024-01-01 05:00",  # 4.5 hour gap
        ], tz="UTC")
        values = pd.Series([0.0, 0.5, 5.0], index=times)
        
        # No gap rejection
        deriv = derivative(values, window="6h", min_periods=2, max_gap=None)
        
        # Should compute derivative despite large gap
        assert deriv.iloc[-1] is not np.nan
    
    def test_max_gap_small_continuous_data(self):
        """Small max_gap accepts continuous data."""
        times = pd.date_range("2024-01-01 00:00", periods=10, freq="10min", tz="UTC")
        values = pd.Series(range(10), index=times, dtype=float)
        
        # Allow gaps up to 30 minutes
        deriv = derivative(values, window="30min", min_periods=2, max_gap="30min")
        
        # All points should have valid derivatives (gaps are only 10 min)
        assert deriv.notna().sum() >= 8
    
    def test_max_gap_sensor_dropout_scenario(self):
        """Realistic scenario: sensor drops out and comes back."""
        times = pd.DatetimeIndex([
            "2024-01-01 00:00",
            "2024-01-01 01:00",
            "2024-01-01 02:00",
            # Sensor offline for 3 hours
            "2024-01-01 05:00",
            "2024-01-01 06:00",
            "2024-01-01 07:00",
        ], tz="UTC")
        # Temperature drops during offline period (misleading derivative)
        values = pd.Series([20.0, 21.0, 22.0, 10.0, 11.0, 12.0], index=times)
        
        # Without max_gap: would compute misleading derivative across the gap
        deriv_no_gap = derivative(values, window="4h", min_periods=2, max_gap=None)
        
        # With max_gap: rejects windows spanning the sensor dropout
        deriv_with_gap = derivative(values, window="4h", min_periods=2, max_gap="2h")
        
        # Point at 05:00 should be rejected with max_gap
        assert pd.isna(deriv_with_gap.loc["2024-01-01 05:00"])
        
        # But later points (06:00, 07:00) should recover
        assert deriv_with_gap.loc["2024-01-01 07:00"] is not np.nan


class TestDerivativeWindowSizes:
    """Tests for different window sizes."""
    
    def test_window_size_affects_smoothing(self):
        """Larger windows produce smoother derivatives."""
        times = pd.date_range("2024-01-01", periods=20, freq="1h", tz="UTC")
        # Add some noise to linear trend
        values = pd.Series(range(20), index=times, dtype=float)
        values += np.random.normal(0, 0.2, 20)
        
        deriv_2h = derivative(values, window="2h", min_periods=2)
        deriv_3h = derivative(values, window="3h", min_periods=2)
        deriv_6h = derivative(values, window="6h", min_periods=2)
        
        # Larger windows should have less variance (more smoothing)
        std_2h = deriv_2h.dropna().std()
        std_3h = deriv_3h.dropna().std()
        std_6h = deriv_6h.dropna().std()
        
        assert std_6h < std_3h < std_2h
    
    def test_window_too_small(self):
        """Very small window with min_periods produces sparse output."""
        times = pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
        values = pd.Series(range(10), index=times, dtype=float)
        
        # Window smaller than sample spacing
        deriv = derivative(values, window="30min", min_periods=2)
        
        # Most points won't have 2 samples in 30min window
        assert deriv.notna().sum() < 5


class TestDerivativeReindex:
    """Tests that derivative correctly handles reindexing to original index."""
    
    def test_preserves_index_with_nans(self):
        """Result has same index as input, even where input had NaN."""
        times = pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
        values = pd.Series(range(10), index=times, dtype=float)
        values.iloc[3:5] = np.nan  # Insert NaN gap
        
        deriv = derivative(values, window="2h", min_periods=2)
        
        # Output index matches input index
        assert deriv.index.equals(values.index)
        # NaN positions in input also NaN in output
        assert deriv.iloc[3:5].isna().all()
    
    def test_output_length_matches_input(self):
        """Output series has same length as input series."""
        times = pd.date_range("2024-01-01", periods=100, freq="15min", tz="UTC")
        values = pd.Series(np.random.randn(100), index=times)
        
        deriv = derivative(values, window="1h", min_periods=3)
        
        assert len(deriv) == len(values)
        assert deriv.index.equals(values.index)
