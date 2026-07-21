"""
test_pressure_series.py — Tests for build_pressure_series_* functions
======================================================================

Tests for the five pressure-series builder functions in rainlib.py:
- build_pressure_series_ha
- build_pressure_series_meteostat
- build_pressure_series_yandex
- build_pressure_series (deprecated wrapper)
- build_pressure_series_legacy

Coverage goals:
1. mmHg → hPa conversion (750 mm Hg ≈ 999.915 hPa, factor 1.33322)
2. All-NaN → None
3. Missing column → None
4. Normal operation with valid data
"""

import numpy as np
import pandas as pd
import pytest

from rainlib import (
    build_pressure_series_ha,
    build_pressure_series_meteostat,
    build_pressure_series_yandex,
    build_pressure_series,
    build_pressure_series_legacy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_grid():
    """Empty DataFrame with datetime index."""
    idx = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
    return pd.DataFrame(index=idx)


@pytest.fixture
def grid_with_ha_pressure():
    """Grid with HA pressure data in hPa."""
    idx = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
    return pd.DataFrame({
        "pressure": [1013.25, 1012.0, 1011.5, np.nan, 1010.0],
        "temperature": [20.0, 21.0, 22.0, 23.0, 24.0],
    }, index=idx)


@pytest.fixture
def grid_with_meteostat_pressure():
    """Grid with Meteostat pressure data in hPa."""
    idx = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
    return pd.DataFrame({
        "ms_pres": [1015.0, 1014.5, np.nan, 1013.0, 1012.5],
        "temperature": [20.0, 21.0, 22.0, 23.0, 24.0],
    }, index=idx)


@pytest.fixture
def grid_with_yandex_pressure():
    """Grid with Yandex pressure data in mm Hg."""
    idx = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
    return pd.DataFrame({
        "yx_pressure_mm": [750.0, 755.0, 760.0, np.nan, 765.0],
        "temperature": [20.0, 21.0, 22.0, 23.0, 24.0],
    }, index=idx)


@pytest.fixture
def grid_with_all_nan_pressure():
    """Grid with all-NaN pressure column."""
    idx = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
    return pd.DataFrame({
        "pressure": [np.nan, np.nan, np.nan, np.nan, np.nan],
        "temperature": [20.0, 21.0, 22.0, 23.0, 24.0],
    }, index=idx)


@pytest.fixture
def grid_with_multiple_sources():
    """Grid with all three pressure sources."""
    idx = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
    return pd.DataFrame({
        "pressure": [1013.25, np.nan, 1011.5, np.nan, 1010.0],
        "ms_pres": [np.nan, 1014.5, np.nan, 1013.0, np.nan],
        "yx_pressure_mm": [750.0, 755.0, 760.0, 765.0, 770.0],
        "temperature": [20.0, 21.0, 22.0, 23.0, 24.0],
    }, index=idx)


# ---------------------------------------------------------------------------
# Tests for build_pressure_series_ha
# ---------------------------------------------------------------------------

def test_build_pressure_series_ha_normal(grid_with_ha_pressure):
    """HA pressure: normal operation with valid data."""
    result = build_pressure_series_ha(grid_with_ha_pressure)
    assert result is not None
    assert isinstance(result, pd.Series)
    assert len(result) == 5
    assert result.iloc[0] == 1013.25
    assert result.iloc[1] == 1012.0
    assert pd.isna(result.iloc[3])
    assert result.iloc[4] == 1010.0


def test_build_pressure_series_ha_missing_column(empty_grid):
    """HA pressure: missing column → None."""
    result = build_pressure_series_ha(empty_grid, ha_pressure_col="pressure")
    assert result is None


def test_build_pressure_series_ha_all_nan(grid_with_all_nan_pressure):
    """HA pressure: all-NaN data → None."""
    result = build_pressure_series_ha(grid_with_all_nan_pressure)
    assert result is None


def test_build_pressure_series_ha_custom_column_name():
    """HA pressure: custom column name."""
    idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    grid = pd.DataFrame({
        "custom_pressure": [1013.0, 1012.0, 1011.0],
    }, index=idx)
    result = build_pressure_series_ha(grid, ha_pressure_col="custom_pressure")
    assert result is not None
    assert len(result) == 3
    assert result.iloc[0] == 1013.0


# ---------------------------------------------------------------------------
# Tests for build_pressure_series_meteostat
# ---------------------------------------------------------------------------

def test_build_pressure_series_meteostat_normal(grid_with_meteostat_pressure):
    """Meteostat pressure: normal operation with valid data."""
    result = build_pressure_series_meteostat(grid_with_meteostat_pressure)
    assert result is not None
    assert isinstance(result, pd.Series)
    assert len(result) == 5
    assert result.iloc[0] == 1015.0
    assert result.iloc[1] == 1014.5
    assert pd.isna(result.iloc[2])
    assert result.iloc[3] == 1013.0


def test_build_pressure_series_meteostat_missing_column(empty_grid):
    """Meteostat pressure: missing column → None."""
    result = build_pressure_series_meteostat(empty_grid)
    assert result is None


def test_build_pressure_series_meteostat_all_nan():
    """Meteostat pressure: all-NaN data → None."""
    idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    grid = pd.DataFrame({
        "ms_pres": [np.nan, np.nan, np.nan],
    }, index=idx)
    result = build_pressure_series_meteostat(grid)
    assert result is None


# ---------------------------------------------------------------------------
# Tests for build_pressure_series_yandex
# ---------------------------------------------------------------------------

def test_build_pressure_series_yandex_normal(grid_with_yandex_pressure):
    """Yandex pressure: normal operation with mmHg → hPa conversion."""
    result = build_pressure_series_yandex(grid_with_yandex_pressure)
    assert result is not None
    assert isinstance(result, pd.Series)
    assert len(result) == 5
    
    # Test mmHg → hPa conversion (750 mm Hg * 1.33322 ≈ 999.915 hPa)
    assert result.iloc[0] == pytest.approx(999.915, rel=1e-5)
    assert result.iloc[1] == pytest.approx(1006.5811, rel=1e-5)
    assert result.iloc[2] == pytest.approx(1013.2472, rel=1e-5)
    assert pd.isna(result.iloc[3])
    assert result.iloc[4] == pytest.approx(1019.9133, rel=1e-5)


def test_build_pressure_series_yandex_conversion_factor():
    """Yandex pressure: verify exact conversion factor (1.33322)."""
    idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    grid = pd.DataFrame({
        "yx_pressure_mm": [750.0, 760.0, 770.0],
    }, index=idx)
    result = build_pressure_series_yandex(grid)
    
    # 750 mm Hg × 1.33322 = 999.915 hPa
    assert result.iloc[0] == 750.0 * 1.33322
    # 760 mm Hg × 1.33322 = 1013.2472 hPa (standard atmosphere)
    assert result.iloc[1] == 760.0 * 1.33322
    # 770 mm Hg × 1.33322 = 1026.5794 hPa
    assert result.iloc[2] == 770.0 * 1.33322


def test_build_pressure_series_yandex_missing_column(empty_grid):
    """Yandex pressure: missing column → None."""
    result = build_pressure_series_yandex(empty_grid)
    assert result is None


def test_build_pressure_series_yandex_all_nan():
    """Yandex pressure: all-NaN data → None."""
    idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    grid = pd.DataFrame({
        "yx_pressure_mm": [np.nan, np.nan, np.nan],
    }, index=idx)
    result = build_pressure_series_yandex(grid)
    assert result is None


# ---------------------------------------------------------------------------
# Tests for build_pressure_series (deprecated wrapper)
# ---------------------------------------------------------------------------

def test_build_pressure_series_wrapper_uses_ha_only(grid_with_multiple_sources):
    """Deprecated wrapper: now only returns HA data (no fallback)."""
    result = build_pressure_series(grid_with_multiple_sources)
    assert result is not None
    
    # Should only return HA data, not filled from other sources
    assert result.iloc[0] == 1013.25
    assert pd.isna(result.iloc[1])  # HA has NaN here
    assert result.iloc[2] == 1011.5
    assert pd.isna(result.iloc[3])  # HA has NaN here
    assert result.iloc[4] == 1010.0


def test_build_pressure_series_wrapper_missing_ha_column(grid_with_meteostat_pressure):
    """Deprecated wrapper: missing HA column → None (no fallback to ms_pres)."""
    result = build_pressure_series(grid_with_meteostat_pressure)
    assert result is None


# ---------------------------------------------------------------------------
# Tests for build_pressure_series_legacy (fallback chain)
# ---------------------------------------------------------------------------

def test_build_pressure_series_legacy_fallback_chain(grid_with_multiple_sources):
    """Legacy: fills from HA → Meteostat → Yandex in order."""
    result = build_pressure_series_legacy(grid_with_multiple_sources)
    assert result is not None
    
    # Index 0: HA = 1013.25, ms = NaN, yx = 750*1.33322
    assert result.iloc[0] == 1013.25  # HA wins
    
    # Index 1: HA = NaN, ms = 1014.5, yx = 755*1.33322
    assert result.iloc[1] == 1014.5  # ms fills
    
    # Index 2: HA = 1011.5, ms = NaN, yx = 760*1.33322
    assert result.iloc[2] == 1011.5  # HA wins
    
    # Index 3: HA = NaN, ms = 1013.0, yx = 765*1.33322
    assert result.iloc[3] == 1013.0  # ms fills
    
    # Index 4: HA = 1010.0, ms = NaN, yx = 770*1.33322
    assert result.iloc[4] == 1010.0  # HA wins


def test_build_pressure_series_legacy_yandex_fallback():
    """Legacy: falls back to Yandex when HA and Meteostat are missing."""
    idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    grid = pd.DataFrame({
        "yx_pressure_mm": [750.0, 760.0, 770.0],
    }, index=idx)
    result = build_pressure_series_legacy(grid)
    assert result is not None
    
    # All values should come from Yandex with conversion
    assert result.iloc[0] == pytest.approx(999.915, rel=1e-5)
    assert result.iloc[1] == pytest.approx(1013.2472, rel=1e-5)
    assert result.iloc[2] == pytest.approx(1026.5794, rel=1e-5)


def test_build_pressure_series_legacy_all_sources_missing(empty_grid):
    """Legacy: all sources missing → None."""
    result = build_pressure_series_legacy(empty_grid)
    assert result is None


def test_build_pressure_series_legacy_all_sources_nan():
    """Legacy: all sources are all-NaN → None."""
    idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    grid = pd.DataFrame({
        "pressure": [np.nan, np.nan, np.nan],
        "ms_pres": [np.nan, np.nan, np.nan],
        "yx_pressure_mm": [np.nan, np.nan, np.nan],
    }, index=idx)
    result = build_pressure_series_legacy(grid)
    assert result is None
