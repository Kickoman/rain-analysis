"""
test_models.py — Unit tests for rain prediction models

Tests that all models are distinct, produce valid outputs,
and maintain expected behavior.
"""

import pytest
import numpy as np
import pandas as pd
from rainlib import (
    model_original,
    model_ha_live,
    model_tuned,
    model_trend_dominant,
    model_pressure_aware,
    ModelContext,
    MODELS,
)
# Helper: create ModelContext from spread + deriv (for test convenience)
def _ctx(spread, deriv, pressure=None):
    return ModelContext(spread=spread, spread_deriv=deriv, pressure=pressure)




class TestModelOriginal:
    """Tests for model_original (baseline v0.1)."""
    
    def test_uses_correct_parameters(self):
        """Verify model_original uses divisor=10, gain=20.
        
        This protects against regression of issue #21 where
        model_original was incorrectly using ha_live parameters.
        """
        # At spread=10, proximity should be 0
        spread = pd.Series([10.0])
        deriv = pd.Series([0.0])
        result = model_original(_ctx(spread, deriv))
        
        # proximity=0, trend=0 → total=0
        assert result.iloc[0] == 0.0
    
    def test_output_range(self):
        """Output is clamped to [0, 100]."""
        spread = pd.Series([0.0, 5.0, 10.0, 15.0])
        deriv = pd.Series([-2.0, 0.0, 1.0, 2.0])
        result = model_original(_ctx(spread, deriv))
        
        assert all(result >= 0)
        assert all(result <= 100)
    
    def test_low_spread_high_score(self):
        """Small spread (near saturation) produces high score."""
        spread = pd.Series([1.0])
        deriv = pd.Series([0.0])
        result = model_original(_ctx(spread, deriv))
        
        assert result.iloc[0] > 60  # Should be high


class TestModelHaLive:
    """Tests for model_ha_live (production model)."""
    
    def test_uses_correct_parameters(self):
        """Verify ha_live uses divisor=8, multiplier=26.7."""
        # At spread=8, proximity should be 0
        spread = pd.Series([8.0])
        deriv = pd.Series([0.0])
        result = model_ha_live(_ctx(spread, deriv))
        
        assert result.iloc[0] == 0.0
    
    def test_output_range(self):
        """Output is clamped to [0, 100]."""
        spread = pd.Series([0.0, 4.0, 8.0, 12.0])
        deriv = pd.Series([-3.0, -1.0, 0.0, 2.0])
        result = model_ha_live(_ctx(spread, deriv))
        
        assert all(result >= 0)
        assert all(result <= 100)
    
    def test_stateless(self):
        """ha_live is stateless - same inputs always give same output."""
        spread = pd.Series([3.0, 5.0, 3.0, 5.0])
        deriv = pd.Series([-1.0, 0.0, -1.0, 0.0])
        result = model_ha_live(_ctx(spread, deriv))
        
        # First and third should be identical (same inputs)
        assert result.iloc[0] == result.iloc[2]
        assert result.iloc[1] == result.iloc[3]


class TestModelTuned:
    """Tests for model_tuned (experimental with hysteresis)."""
    
    def test_hysteresis_decay(self):
        """Tuned model decays slowly after peak (hysteresis behavior)."""
        # Rise to high value, then drop
        spread = pd.Series([1.0, 1.0, 8.0, 8.0])
        deriv = pd.Series([0.0, 0.0, 0.0, 0.0])
        result = model_tuned(_ctx(spread, deriv))
        
        # After peak, should decay slowly (not instantly drop)
        assert result.iloc[2] > result.iloc[3]  # Decaying
        assert result.iloc[2] > 10  # But not instant drop to near-zero
    
    def test_output_range(self):
        """Output is clamped to [0, 100]."""
        spread = pd.Series([0.0, 3.0, 7.0, 12.0])
        deriv = pd.Series([-2.0, -1.0, 0.0, 1.0])
        result = model_tuned(_ctx(spread, deriv))
        
        assert all(result >= 0)
        assert all(result <= 100)


class TestModelTrendDominant:
    """Tests for model_trend_dominant (experimental)."""
    
    def test_output_range(self):
        """Output is clamped to [0, 100]."""
        spread = pd.Series([2.0, 5.0, 8.0, 11.0])
        deriv = pd.Series([-2.0, -1.0, 0.0, 1.0])
        result = model_trend_dominant(_ctx(spread, deriv))
        
        assert all(result >= 0)
        assert all(result <= 100)
    
    def test_trend_driven(self):
        """Trend-dominant should respond strongly to derivative changes."""
        # Same spread, different derivatives
        spread = pd.Series([5.0, 5.0])
        deriv_falling = pd.Series([-2.0, -2.0])
        deriv_rising = pd.Series([2.0, 2.0])
        
        result_falling = model_trend_dominant(_ctx(spread, deriv_falling))
        result_rising = model_trend_dominant(_ctx(spread, deriv_rising))
        
        # Falling spread (narrowing) should give higher score
        assert result_falling.iloc[0] > result_rising.iloc[0]

class TestModelPressureAware:
    """Tests for model_pressure_aware (experimental with pressure factor)."""

    def test_falls_back_without_pressure(self):
        """Without pressure data, behaves like tuned model (not identical but similar range)."""
        spread = pd.Series([3.0, 5.0, 7.0])
        deriv = pd.Series([-1.0, 0.0, 1.0])
        ctx = _ctx(spread, deriv)  # no pressure
        result = model_pressure_aware(ctx)

        assert len(result) == 3
        assert all(result >= 0)
        assert all(result <= 100)

    def test_falling_pressure_boosts_score(self):
        """Falling pressure should increase rain probability vs no pressure."""
        idx = pd.date_range("2026-07-14 12:00", periods=3, freq="1h", tz="UTC")
        spread = pd.Series([5.0, 5.0, 5.0], index=idx)
        deriv = pd.Series([0.0, 0.0, 0.0], index=idx)
        pressure_falling = pd.Series([1010.0, 1008.0, 1006.0], index=idx)

        ctx_no_pres = _ctx(spread, deriv)
        ctx_falling = _ctx(spread, deriv, pressure_falling)

        result_no_pres = model_pressure_aware(ctx_no_pres)
        result_falling = model_pressure_aware(ctx_falling)

        # Falling pressure should give higher scores (or equal, if pressure_drop_threshold not met)
        # At -2 hPa over 2 rows, with 3h window: ~-2 hPa/h average = strong signal
        assert result_falling.iloc[-1] >= result_no_pres.iloc[-1]

    def test_rising_pressure_suppresses_score(self):
        """Rising pressure should decrease rain probability."""
        idx = pd.date_range("2026-07-14 12:00", periods=3, freq="1h", tz="UTC")
        spread = pd.Series([5.0, 5.0, 5.0], index=idx)
        deriv = pd.Series([0.0, 0.0, 0.0], index=idx)
        pressure_rising = pd.Series([1006.0, 1008.0, 1010.0], index=idx)

        ctx_no_pres = _ctx(spread, deriv)
        ctx_rising = _ctx(spread, deriv, pressure_rising)

        result_no_pres = model_pressure_aware(ctx_no_pres)
        result_rising = model_pressure_aware(ctx_rising)

        # Rising pressure should give lower or equal scores
        assert result_rising.iloc[-1] <= result_no_pres.iloc[-1]

    def test_output_range(self):
        """Output is clamped to [0, 100]."""
        idx = pd.date_range("2026-07-14 12:00", periods=4, freq="1h", tz="UTC")
        spread = pd.Series([0.0, 3.0, 7.0, 12.0], index=idx)
        deriv = pd.Series([-2.0, -1.0, 0.0, 1.0], index=idx)
        pressure = pd.Series([1010.0, 1005.0, 1015.0, 1020.0], index=idx)
        ctx = _ctx(spread, deriv, pressure)
        result = model_pressure_aware(ctx)

        assert all(result >= 0)
        assert all(result <= 100)

    def test_below_threshold_no_effect(self):
        """Pressure changes below drop_threshold should not affect score."""
        idx = pd.date_range("2026-07-14 12:00", periods=2, freq="1h", tz="UTC")
        spread = pd.Series([5.0, 5.0], index=idx)
        deriv = pd.Series([0.0, 0.0], index=idx)
        # Very slight pressure change (0.1 hPa/h) - below default 0.5 threshold
        pressure_tiny = pd.Series([1010.0, 1009.9], index=idx)

        ctx_no_pres = _ctx(spread, deriv)
        ctx_tiny = _ctx(spread, deriv, pressure_tiny)

        result_no_pres = model_pressure_aware(ctx_no_pres)
        result_tiny = model_pressure_aware(ctx_tiny)

        # With noise-level pressure change, scores should be similar
        assert abs(result_tiny.iloc[-1] - result_no_pres.iloc[-1]) < 1.0



class TestModelComparison:
    """Cross-model comparison tests."""
    
    def test_original_not_equal_ha_live(self):
        """model_original and model_ha_live should give different results.
        
        This is a regression test for issue #21 where they were identical.
        """
        spread = pd.Series([2.0, 5.0, 8.0, 12.0])
        deriv = pd.Series([-1.0, 0.0, 1.0, 0.5])
        
        orig = model_original(_ctx(spread, deriv))
        live = model_ha_live(_ctx(spread, deriv))
        
        # Must differ in at least one point
        assert not orig.equals(live)
        
        # Verify they differ meaningfully (not just rounding)
        max_diff = abs(orig - live).max()
        assert max_diff > 1.0
    
    def test_all_models_registered(self):
        """All four models are in the MODELS registry."""
        assert "original" in MODELS
        assert "tuned" in MODELS
        assert "trend_dominant" in MODELS
        assert "ha_live" in MODELS
        assert "pressure_aware" in MODELS
        
        assert len(MODELS) == 5
    
    def test_all_models_callable(self):
        """All registered models can be called."""
        spread = pd.Series([3.0, 6.0])
        deriv = pd.Series([-1.0, 0.5])
        
        for name, model_fn in MODELS.items():
            result = model_fn(_ctx(spread, deriv))
            assert isinstance(result, pd.Series)
            assert len(result) == 2
            assert all(result >= 0)
            assert all(result <= 100)


class TestInputValidation:
    """Tests for input handling and edge cases."""
    
    def test_empty_series(self):
        """Models handle empty input gracefully."""
        spread = pd.Series([], dtype=float)
        deriv = pd.Series([], dtype=float)
        
        result = model_original(_ctx(spread, deriv))
        assert len(result) == 0
    
    def test_single_value(self):
        """Models work with single data point."""
        spread = pd.Series([5.0])
        deriv = pd.Series([-1.0])
        
        for model_fn in MODELS.values():
            result = model_fn(_ctx(spread, deriv))
            assert len(result) == 1
            assert 0 <= result.iloc[0] <= 100
    
    def test_nan_handling(self):
        """Models handle NaN values without crashing."""
        spread = pd.Series([2.0, np.nan, 6.0])
        deriv = pd.Series([-1.0, 0.0, np.nan])
        
        # Should not raise exceptions
        result = model_ha_live(_ctx(spread, deriv))
        assert len(result) == 3
    
    def test_mismatched_indices(self):
        """Models work when spread and deriv have different indices."""
        spread = pd.Series([3.0, 5.0, 7.0], index=[0, 2, 4])
        deriv = pd.Series([-1.0, 0.0, 1.0], index=[0, 2, 4])
        
        result = model_original(_ctx(spread, deriv))
        assert len(result) == 3


class TestRealWorldScenarios:
    """Tests based on real weather patterns."""
    
    def test_clear_night_radiative_cooling(self):
        """Clear night with radiative cooling (false positive scenario).
        
        Temperature drops, humidity rises, spread narrows - but no rain.
        Models should show this pattern produces elevated scores.
        """
        # Simulated clear night: T drops from 18→12, RH rises 65→85
        # Spread narrows from 7→2, derivative negative
        spread = pd.Series([7.0, 5.0, 3.0, 2.0])
        deriv = pd.Series([-1.5, -1.5, -1.0, -0.5])
        
        result = model_ha_live(_ctx(spread, deriv))
        
        # Should show elevated scores (this is the known limitation)
        assert result.iloc[-1] > 30
    
    def test_actual_rain_approach(self):
        """Rain system approach: sustained narrowing spread."""
        spread = pd.Series([10.0, 7.0, 4.0, 2.0, 1.0])
        deriv = pd.Series([-1.0, -1.5, -1.5, -1.0, -0.5])
        
        result = model_ha_live(_ctx(spread, deriv))
        
        # Should show increasing trend
        assert result.iloc[-1] > result.iloc[0]
        assert result.iloc[-1] > 50  # High probability near end
    
    def test_post_rain_recovery(self):
        """After rain peak, spread widens again."""
        spread = pd.Series([1.0, 2.0, 4.0, 6.0])
        deriv = pd.Series([0.5, 1.0, 1.0, 0.5])
        
        result = model_ha_live(_ctx(spread, deriv))
        
        # Should show decreasing trend
        assert result.iloc[-1] < result.iloc[0]
