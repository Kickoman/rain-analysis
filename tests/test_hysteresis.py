"""
test_hysteresis.py — Comprehensive tests for hysteresis behavior in stateful models

Tests exact multi-step convergence, different decay rates, and edge cases.
Addresses issue #156: lack of exact-value and multi-step test coverage.
"""

import pytest
import pandas as pd
from rainlib import model_tuned, model_pressure_aware, ModelContext, ModelParams


def _ctx(spread, deriv, pressure=None):
    """Helper: create ModelContext from spread + deriv."""
    return ModelContext(spread=spread, spread_deriv=deriv, pressure=pressure)


class TestHysteresisExactValues:
    """Test exact hysteresis formula: total = prev - (prev - raw) * decay"""

    def test_exact_decay_sequence_default(self):
        """Verify exact multi-step decay with default hysteresis_decay=0.30."""
        # Setup: high score at step 0, then raw drops to zero
        # Step 0: raw=high → total=high (first value, prev=None)
        # Steps 1-4: raw=0 → total decays by formula
        
        # Create inputs that give high raw score at step 0, then ≈ 0 after
        spread = pd.Series([0.1, 10.0, 10.0, 10.0, 10.0])  # high proximity → low
        deriv = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0])
        
        result = model_tuned(_ctx(spread, deriv))
        
        # Step 0: should be high (proximity-based score)
        r0 = result.iloc[0]
        assert r0 > 70  # High initial value
        
        # Steps 1-4: raw ≈ 0 (spread=10 >> divisor=7)
        # Formula: total = prev - (prev - 0) * 0.30 = prev * 0.70
        # Expected sequence: r0, r0*0.7, r0*0.49, r0*0.343, r0*0.2401
        
        tolerance = 1.0  # Allow 1 point rounding tolerance
        
        assert abs(result.iloc[1] - r0 * 0.70) < tolerance
        assert abs(result.iloc[2] - r0 * 0.49) < tolerance
        assert abs(result.iloc[3] - r0 * 0.343) < tolerance
        assert abs(result.iloc[4] - r0 * 0.2401) < tolerance
    
    def test_exact_decay_sequence_slow(self):
        """Verify exact decay with slow decay rate (0.1)."""
        # With decay=0.1, hysteresis is stronger (slower decay)
        spread = pd.Series([0.1, 10.0, 10.0, 10.0, 10.0])
        deriv = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0])
        
        params = ModelParams()
        params.hysteresis_decay = 0.1
        
        result = model_tuned(_ctx(spread, deriv), p=params)
        
        r0 = result.iloc[0]
        assert r0 > 70
        
        # Formula: total = prev * (1 - 0.1) = prev * 0.9
        # Expected: r0, r0*0.9, r0*0.81, r0*0.729, r0*0.6561
        
        tolerance = 1.0
        assert abs(result.iloc[1] - r0 * 0.9) < tolerance
        assert abs(result.iloc[2] - r0 * 0.81) < tolerance
        assert abs(result.iloc[3] - r0 * 0.729) < tolerance
        assert abs(result.iloc[4] - r0 * 0.6561) < tolerance
    
    def test_exact_decay_sequence_fast(self):
        """Verify exact decay with fast decay rate (0.8)."""
        # With decay=0.8, hysteresis is weaker (faster decay)
        spread = pd.Series([0.1, 10.0, 10.0, 10.0, 10.0])
        deriv = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0])
        
        params = ModelParams()
        params.hysteresis_decay = 0.8
        
        result = model_tuned(_ctx(spread, deriv), p=params)
        
        r0 = result.iloc[0]
        assert r0 > 70
        
        # Formula: total = prev * (1 - 0.8) = prev * 0.2
        # Expected: r0, r0*0.2, r0*0.04, r0*0.008, r0*0.0016
        
        tolerance = 1.0
        assert abs(result.iloc[1] - r0 * 0.2) < tolerance
        assert abs(result.iloc[2] - r0 * 0.04) < tolerance
        # Steps 3-4 will be very small, just verify they decay
        assert result.iloc[3] < result.iloc[2]
        assert result.iloc[4] < result.iloc[3]


class TestHysteresisConvergence:
    """Test convergence behavior with different decay rates."""

    def test_slow_decay_convergence(self):
        """Slow decay (0.1) should converge slowly to new steady state."""
        # Start high, then settle to mid-level raw score
        spread = pd.Series([0.1] + [5.0] * 10)  # More steps to see convergence
        deriv = pd.Series([0.0] * 11)
        
        params = ModelParams()
        params.hysteresis_decay = 0.1
        
        result = model_tuned(_ctx(spread, deriv), p=params)
        
        r0 = result.iloc[0]  # Initial high value
        
        # Calculate what raw score would be at steady state (without hysteresis memory)
        # Use a fresh model with decay=1.0 to get instant raw value
        params_instant = ModelParams()
        params_instant.hysteresis_decay = 1.0
        result_instant = model_tuned(_ctx(pd.Series([5.0]), pd.Series([0.0])), p=params_instant)
        raw_target = result_instant.iloc[0]
        
        # With slow decay, should still be significantly above target after many steps
        # Formula: value[n] = target + (r0 - target) * (0.9)^n
        # After 10 steps: (0.9)^10 = 0.349, so should retain 35% of initial gap
        
        gap_initial = r0 - raw_target
        gap_at_10 = result.iloc[10] - raw_target
        
        # Should have decayed but not fully converged
        assert gap_at_10 < gap_initial  # Making progress
        assert gap_at_10 > gap_initial * 0.2  # But still far from target (>20% gap remains)
    
    def test_fast_decay_convergence(self):
        """Fast decay (0.8) should converge quickly to new steady state."""
        # Start high, then settle to mid-level raw score
        spread = pd.Series([0.1, 5.0, 5.0, 5.0, 5.0])
        deriv = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0])
        
        params = ModelParams()
        params.hysteresis_decay = 0.8
        
        result = model_tuned(_ctx(spread, deriv), p=params)
        
        # With decay=0.8, converges much faster
        # After 4 steps: gap = initial_gap * (0.2)^4 = 0.0016
        # Should be very close to raw value
        
        # Calculate what stateless model would give
        params_stateless = ModelParams()
        params_stateless.hysteresis_decay = 1.0  # No hysteresis
        result_stateless = model_tuned(_ctx(spread, deriv), p=params_stateless)
        
        # At step 4, fast-decay should be very close to stateless
        assert abs(result.iloc[4] - result_stateless.iloc[4]) < 5.0


class TestHysteresisEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_no_hysteresis_decay_one(self):
        """With decay=1.0, behaves like stateless model (instant response)."""
        spread = pd.Series([0.1, 10.0, 10.0])
        deriv = pd.Series([0.0, 0.0, 0.0])
        
        params = ModelParams()
        params.hysteresis_decay = 1.0
        
        result = model_tuned(_ctx(spread, deriv), p=params)
        
        # Should drop instantly to raw value (no hysteresis effect)
        # Step 1 and 2 should be same (raw hasn't changed)
        assert abs(result.iloc[1] - result.iloc[2]) < 0.1
    
    def test_frozen_hysteresis_decay_zero(self):
        """With decay=0.0, output freezes at peak (maximum hysteresis)."""
        spread = pd.Series([0.1, 10.0, 10.0, 10.0])
        deriv = pd.Series([0.0, 0.0, 0.0, 0.0])
        
        params = ModelParams()
        params.hysteresis_decay = 0.0
        
        result = model_tuned(_ctx(spread, deriv), p=params)
        
        r0 = result.iloc[0]
        
        # With decay=0, total = prev - (prev - raw) * 0 = prev
        # Output should stay frozen at r0
        assert abs(result.iloc[1] - r0) < 0.1
        assert abs(result.iloc[2] - r0) < 0.1
        assert abs(result.iloc[3] - r0) < 0.1
    
    def test_rising_raw_bypasses_hysteresis(self):
        """When raw > prev, output rises instantly (no decay applied)."""
        # Step 0: low raw
        # Step 1: high raw (should jump up instantly)
        # Step 2: same high raw (should stay)
        spread = pd.Series([10.0, 0.1, 0.1])
        deriv = pd.Series([0.0, 0.0, 0.0])
        
        result = model_tuned(_ctx(spread, deriv))
        
        # Step 0: low (spread=10)
        assert result.iloc[0] < 20
        
        # Step 1: should jump up instantly (raw > prev, no hysteresis)
        assert result.iloc[1] > 70
        
        # Step 2: should stay high (raw still high)
        assert abs(result.iloc[1] - result.iloc[2]) < 5.0
    
    def test_partial_convergence_to_nonzero_target(self):
        """Verify convergence when raw target is not zero."""
        # Start at high value, drop to steady raw mid-level
        spread = pd.Series([1.0, 4.0, 4.0, 4.0, 4.0, 4.0])
        deriv = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        
        params = ModelParams()
        params.hysteresis_decay = 0.3
        
        result = model_tuned(_ctx(spread, deriv), p=params)
        
        r0 = result.iloc[0]  # Initial high value
        
        # Calculate raw target using instant decay
        params_instant = ModelParams()
        params_instant.hysteresis_decay = 1.0
        result_instant = model_tuned(_ctx(pd.Series([4.0]), pd.Series([0.0])), p=params_instant)
        raw_target = result_instant.iloc[0]
        
        # Should converge toward target, monotonically decreasing
        assert result.iloc[0] > result.iloc[1]
        assert result.iloc[1] > result.iloc[2]
        assert result.iloc[2] > result.iloc[3]
        assert result.iloc[3] > result.iloc[4]
        assert result.iloc[4] > result.iloc[5]
        
        # Final value should be closer to target than step 1
        gap_step1 = abs(result.iloc[1] - raw_target)
        gap_final = abs(result.iloc[5] - raw_target)
        assert gap_final < gap_step1


class TestPressureAwareHysteresis:
    """Test that pressure_aware model also has correct hysteresis behavior."""

    def test_pressure_aware_has_hysteresis(self):
        """Pressure-aware model should also exhibit hysteresis decay."""
        idx = pd.date_range("2026-07-21 12:00", periods=5, freq="1h", tz="UTC")
        spread = pd.Series([0.1, 10.0, 10.0, 10.0, 10.0], index=idx)
        deriv = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0], index=idx)
        pressure = pd.Series([1010.0, 1010.0, 1010.0, 1010.0, 1010.0], index=idx)
        
        result = model_pressure_aware(_ctx(spread, deriv, pressure))
        
        r0 = result.iloc[0]
        assert r0 > 70  # High initial value
        
        # Should decay with hysteresis (not instant drop)
        assert result.iloc[1] > result.iloc[2]
        assert result.iloc[2] > result.iloc[3]
        
        # Should not drop instantly to near-zero
        assert result.iloc[1] > r0 * 0.5
    
    def test_pressure_aware_exact_decay(self):
        """Verify pressure_aware follows exact decay formula."""
        idx = pd.date_range("2026-07-21 12:00", periods=5, freq="1h", tz="UTC")
        spread = pd.Series([0.1, 10.0, 10.0, 10.0, 10.0], index=idx)
        deriv = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0], index=idx)
        pressure = pd.Series([1010.0, 1010.0, 1010.0, 1010.0, 1010.0], index=idx)
        
        params = ModelParams()
        params.hysteresis_decay = 0.3
        
        result = model_pressure_aware(_ctx(spread, deriv, pressure), p=params)
        
        r0 = result.iloc[0]
        
        # Decay formula should match: total = prev * 0.7 (when raw ≈ 0)
        tolerance = 2.0  # Slightly higher tolerance due to pressure calculations
        
        assert abs(result.iloc[1] - r0 * 0.70) < tolerance
        assert abs(result.iloc[2] - r0 * 0.49) < tolerance
        assert abs(result.iloc[3] - r0 * 0.343) < tolerance


class TestHysteresisWithNaN:
    """Test hysteresis behavior with missing data."""

    def test_nan_preserves_previous_state(self):
        """NaN spread should preserve previous output value."""
        spread = pd.Series([0.1, float('nan'), 10.0])
        deriv = pd.Series([0.0, 0.0, 0.0])
        
        result = model_tuned(_ctx(spread, deriv))
        
        # Step 0: high value
        r0 = result.iloc[0]
        assert r0 > 70
        
        # Step 1: NaN spread → should preserve r0
        assert abs(result.iloc[1] - r0) < 0.1
        
        # Step 2: valid spread, should start decaying from r0
        assert result.iloc[2] < r0
        assert result.iloc[2] > r0 * 0.5  # Hysteresis keeps it above instant drop


class TestHysteresisComparison:
    """Compare different decay rates side-by-side."""

    def test_decay_rate_comparison(self):
        """Compare convergence speed between decay=0.1 and decay=0.8."""
        spread = pd.Series([0.1, 10.0, 10.0, 10.0, 10.0])
        deriv = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0])
        
        params_slow = ModelParams()
        params_slow.hysteresis_decay = 0.1
        
        params_fast = ModelParams()
        params_fast.hysteresis_decay = 0.8
        
        result_slow = model_tuned(_ctx(spread, deriv), p=params_slow)
        result_fast = model_tuned(_ctx(spread, deriv), p=params_fast)
        
        # Both start at same value
        assert abs(result_slow.iloc[0] - result_fast.iloc[0]) < 0.1
        
        # After step 1, fast should have decayed more
        assert result_fast.iloc[1] < result_slow.iloc[1]
        
        # Gap should widen at step 2
        gap_step1 = result_slow.iloc[1] - result_fast.iloc[1]
        gap_step2 = result_slow.iloc[2] - result_fast.iloc[2]
        assert gap_step2 > gap_step1
