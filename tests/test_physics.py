"""
test_physics.py — Unit tests for physics primitives

Tests dew_point, spread, absolute_humidity, humidex calculations
against known values and edge cases.
"""

import pytest
import numpy as np
import pandas as pd
from rainlib import (
    dew_point,
    dew_point_spread,
    absolute_humidity,
    humidex,
    MAGNUS_A,
    MAGNUS_B
)


class TestDewPoint:
    """Tests for dew_point calculation."""
    
    def test_known_value_20c_50rh(self):
        """At 20°C and 50% RH, dew point ≈ 9.3°C"""
        dp = dew_point(20.0, 50.0)
        assert abs(dp - 9.3) < 0.2
    
    def test_saturation_100rh(self):
        """At 100% RH, dew point equals temperature."""
        for temp in [0, 10, 15, 20, 25]:
            dp = dew_point(temp, 100.0)
            assert abs(dp - temp) < 0.1
    
    def test_very_dry_air(self):
        """At low RH, dew point should be well below temperature."""
        dp = dew_point(25.0, 20.0)
        # At 25°C and 20% RH, dew point is around 0.5°C (not negative)
        assert dp < 5  # Significantly below temperature
        assert dp < 25  # Well below actual temperature
    
    def test_negative_temperatures(self):
        """Dew point calculation works for freezing temperatures."""
        dp = dew_point(-5.0, 80.0)
        assert -10 < dp < -5
    
    def test_vectorized_series(self):
        """Dew point works with pandas Series."""
        temps = pd.Series([10.0, 15.0, 20.0, 25.0])
        rhs = pd.Series([60.0, 70.0, 80.0, 90.0])
        dps = dew_point(temps, rhs)
        assert isinstance(dps, np.ndarray)
        assert len(dps) == 4
        assert all(dps < temps.values)  # Dew point always <= temperature


class TestDewPointSpread:
    """Tests for dew_point_spread calculation."""
    
    def test_spread_positive(self):
        """Spread is positive when air is not saturated."""
        spread = dew_point_spread(20.0, 50.0)
        assert spread > 0
    
    def test_spread_zero_at_saturation(self):
        """Spread is zero at 100% RH."""
        spread = dew_point_spread(15.0, 100.0)
        assert abs(spread) < 0.1
    
    def test_spread_increases_with_dryness(self):
        """Spread increases as RH decreases."""
        spread_80 = dew_point_spread(20.0, 80.0)
        spread_60 = dew_point_spread(20.0, 60.0)
        spread_40 = dew_point_spread(20.0, 40.0)
        assert spread_40 > spread_60 > spread_80


class TestAbsoluteHumidity:
    """Tests for absolute_humidity calculation."""
    
    def test_known_value(self):
        """Test against known psychrometric value."""
        # At 20°C and 60% RH, AH ≈ 10.4 g/m³
        ah = absolute_humidity(20.0, 60.0)
        assert 10.0 < ah < 11.0
    
    def test_increases_with_temperature(self):
        """At same RH, warmer air holds more absolute moisture."""
        ah_10 = absolute_humidity(10.0, 60.0)
        ah_20 = absolute_humidity(20.0, 60.0)
        ah_30 = absolute_humidity(30.0, 60.0)
        assert ah_30 > ah_20 > ah_10
    
    def test_uses_magnus_constants(self):
        """Verify calculation uses MAGNUS_A and MAGNUS_B constants.
        
        This test protects against regression of issue #19 where
        hardcoded constants were used instead of the module constants.
        """
        t, rh = 20.0, 60.0
        ah = absolute_humidity(t, rh)
        
        # Manual calculation with module constants
        vp = 6.112 * np.exp(MAGNUS_A * t / (MAGNUS_B + t)) * rh / 100.0
        expected = 216.7 * vp / (273.15 + t)
        
        assert abs(ah - expected) < 0.01


class TestHumidex:
    """Tests for humidex 'feels like' calculation."""
    
    def test_humidex_higher_than_temp(self):
        """Humidex should be higher than actual temperature in humid conditions."""
        temp = 25.0
        dp = dew_point(25.0, 70.0)
        hx = humidex(temp, dp)
        assert hx > temp
    
    def test_humidex_low_in_dry_air(self):
        """In dry air, humidex is close to actual temperature."""
        temp = 25.0
        dp = dew_point(25.0, 30.0)
        hx = humidex(temp, dp)
        # Humidex should be close to temp when dry
        assert abs(hx - temp) < 5
    
    def test_vectorized(self):
        """Humidex works with arrays."""
        temps = np.array([20.0, 25.0, 30.0])
        dps = np.array([15.0, 18.0, 22.0])
        hx = humidex(temps, dps)
        assert len(hx) == 3
        assert all(hx >= temps)


class TestEdgeCases:
    """Edge cases and boundary conditions."""
    
    def test_zero_humidity(self):
        """Very low humidity (clipped to 1e-3) should not crash."""
        dp = dew_point(20.0, 0.0)
        assert not np.isnan(dp)
        assert dp < -20  # Extremely dry
    
    def test_rh_over_100(self):
        """RH values slightly over 100% are clipped."""
        dp = dew_point(20.0, 105.0)
        assert abs(dp - 20.0) < 0.1
    
    def test_nan_handling(self):
        """NaN inputs produce NaN outputs gracefully."""
        dp = dew_point(np.nan, 50.0)
        assert np.isnan(dp)
        
        dp = dew_point(20.0, np.nan)
        assert np.isnan(dp)
