"""
test_end_to_end_pipeline.py — Integration tests for the full analysis pipeline
================================================================================

Tests the complete data flow: load → grid → label → model → metrics → threshold.
Uses small synthetic fixtures to verify that all components work together correctly.

Covers:
- Happy path: minimal valid pipeline
- Edge cases: NaN handling, empty data
- Output validation: shapes, ranges, metric sanity
- Regression protection: ensure changes don't break the pipeline

Author: OneKraby
Created: 2026-07-22 (addresses issue #161)
"""

import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import pytest

import rainlib as rl
from rainlib import ModelParams, ModelContext, MODELS


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_ha_data():
    """Minimal Home Assistant sensor data (10 rows, hourly)."""
    base_time = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    times = [base_time + timedelta(hours=i) for i in range(10)]
    
    return pd.DataFrame({
        'time': times,
        'temp': [20.0 + i * 0.5 for i in range(10)],  # Increasing temp
        'rh': [60.0 - i * 2 for i in range(10)],      # Decreasing RH
        'pressure': [1013.0 + i * 0.3 for i in range(10)],  # Slight pressure increase
    }).set_index('time')


@pytest.fixture
def synthetic_openmeteo_data(tmp_path):
    """Minimal OpenMeteo ground truth (10 rows, hourly) as JSON file."""
    base_time = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    times = [base_time + timedelta(hours=i) for i in range(10)]
    
    # Rain in hours 3-5
    precip = [0.0, 0.0, 0.0, 0.5, 1.2, 0.8, 0.0, 0.0, 0.0, 0.0]
    
    json_path = tmp_path / "openmeteo_test.json"
    
    import json
    with open(json_path, 'w') as f:
        json.dump({
            "latitude": 50.0,
            "longitude": 30.0,
            "utc_offset_seconds": 0,
            "hourly": {
                "time": [t.strftime("%Y-%m-%dT%H:%M") for t in times],
                "temperature_2m": [19.0 + i * 0.5 for i in range(10)],
                "precipitation": precip,
            }
        }, f)
    
    return str(json_path)


# ---------------------------------------------------------------------------
# End-to-end pipeline tests
# ---------------------------------------------------------------------------

def test_minimal_pipeline_happy_path(synthetic_ha_data, synthetic_openmeteo_data):
    """
    Happy path: build_grid → label_rain → run all models → score_models → recommend_threshold.
    
    Verifies:
    - Grid has expected shape
    - Rain labels are correct (based on precipitation threshold)
    - All models return values in [0, 100]
    - Metrics are computed without errors
    - Threshold recommendation completes
    """
    # Step 1: Load OpenMeteo data
    om_df = rl.load_open_meteo(synthetic_openmeteo_data)
    
    # Step 2: Build grid
    grid = rl.build_grid(
        ha_wide_df=synthetic_ha_data,
        om_df=om_df,
    )
    
    assert isinstance(grid, pd.DataFrame), "build_grid should return DataFrame"
    assert len(grid) > 0, "Grid should not be empty"
    assert 'temp' in grid.columns, "Grid should have temp column"
    assert 'rh' in grid.columns, "Grid should have rh column"
    assert 'pressure' in grid.columns, "Grid should have pressure column"
    assert 'om_temp' in grid.columns, "Grid should have OpenMeteo temperature"
    assert 'om_precip' in grid.columns, "Grid should have OpenMeteo precipitation"
    
    # Step 3: Label rain
    grid['rain_truth'] = rl.label_rain(grid, precip_col='om_precip', threshold_mm=0.1)
    
    assert 'rain_truth' in grid.columns, "label_rain should add rain_truth column"
    
    # Count rain hours
    rain_hours = (grid['rain_truth'] == 1.0).sum()
    no_rain_hours = (grid['rain_truth'] == 0.0).sum()
    
    assert rain_hours > 0, "Should detect some rain hours"
    assert no_rain_hours > 0, "Should detect some no-rain hours"
    
    # Step 4: Compute features
    grid['spread'] = rl.dew_point_spread(grid['temp'], grid['rh'])
    grid['spread_deriv'] = rl.derivative(grid['spread'], window='3h')
    grid['abs_humidity'] = rl.absolute_humidity(grid['temp'], grid['rh'])
    
    assert 'spread' in grid.columns, "Should compute spread"
    assert 'spread_deriv' in grid.columns, "Should compute spread derivative"
    assert grid['spread'].notna().sum() > 0, "Spread should have valid values"
    
    # Step 5: Run all models
    params = ModelParams()
    ctx = ModelContext(
        spread=grid['spread'],
        spread_deriv=grid['spread_deriv'],
        abs_humidity=grid['abs_humidity'],
        temp=grid['temp'],
        pressure=grid['pressure'],
    )
    
    for model_name, model_func in MODELS.items():
        col_name = f'model_{model_name}'
        grid[col_name] = model_func(ctx, params)
        
        # Validate model output
        assert col_name in grid.columns, f"Model {model_name} should add column"
        valid_values = grid[col_name].dropna()
        
        if len(valid_values) > 0:
            assert (valid_values >= 0).all(), f"Model {model_name} should return values >= 0"
            assert (valid_values <= 100).all(), f"Model {model_name} should return values <= 100"
    
    # Step 6: Score models
    model_cols = [f'model_{name}' for name in MODELS.keys()]
    
    for col in model_cols:
        # Check that we can compute metrics without errors
        try:
            # Convert rain_truth to boolean for confusion_at_threshold
            truth_bool = grid['rain_truth'] == 1.0
            conf = rl.confusion_at_threshold(grid[col], truth_bool, threshold=50)
            assert 'precision' in conf, f"Should compute precision for {col}"
            assert 'recall' in conf, f"Should compute recall for {col}"
            assert 'f1' in conf, f"Should compute F1 for {col}"
            assert conf['n'] > 0, f"Should have samples for {col}"
        except Exception as e:
            pytest.fail(f"Failed to score {col}: {e}")
    
    # Step 7: Threshold recommendation
    for col in model_cols:
        valid_mask = grid[col].notna() & grid['rain_truth'].notna()
        if valid_mask.sum() > 0:
            try:
                truth_bool = grid.loc[valid_mask, 'rain_truth'] == 1.0
                rec = rl.recommend_threshold(
                    grid.loc[valid_mask, col],
                    truth_bool,
                    beta=1.0,
                )
                assert 'best_threshold' in rec, f"Should recommend threshold for {col}"
                assert 'precision' in rec, f"Should report precision for {col}"
                assert 'recall' in rec, f"Should report recall for {col}"
                assert rec["best_threshold"] is None or (0 <= rec["best_threshold"] <= 100), f"Threshold should be None or in [0, 100] for {col}"
            except Exception as e:
                pytest.fail(f"Failed threshold recommendation for {col}: {e}")


def test_pipeline_with_nans(synthetic_ha_data, synthetic_openmeteo_data):
    """
    Pipeline with NaN values in input data.
    
    Verifies that the pipeline handles missing data gracefully:
    - Grid construction tolerates NaNs
    - Models handle missing features
    - Metrics computation excludes NaN predictions
    """
    # Introduce NaNs in HA data
    ha_with_nans = synthetic_ha_data.copy()
    ha_with_nans.loc[ha_with_nans.index[2:4], 'temp'] = np.nan
    ha_with_nans.loc[ha_with_nans.index[5:7], 'rh'] = np.nan
    
    # Load and build grid
    om_df = rl.load_open_meteo(synthetic_openmeteo_data)
    grid = rl.build_grid(
        ha_wide_df=ha_with_nans,
        om_df=om_df,
    )
    
    assert len(grid) > 0, "Grid should not be empty even with NaNs"
    
    # Label rain
    grid['rain_truth'] = rl.label_rain(grid, precip_col='om_precip', threshold_mm=0.1)
    
    # Compute features (will propagate NaNs)
    grid['spread'] = rl.dew_point_spread(grid['temp'], grid['rh'])
    grid['spread_deriv'] = rl.derivative(grid['spread'], window='3h')
    
    # Run a simple model
    params = ModelParams()
    ctx = ModelContext(
        spread=grid['spread'],
        spread_deriv=grid['spread_deriv'],
        abs_humidity=grid.get('abs_humidity'),
        temp=grid.get('temp'),
        pressure=grid.get('pressure'),
    )
    
    grid['model_original'] = rl.model_original(ctx, params)
    
    # Verify that model produces some valid values despite NaNs
    valid_predictions = grid['model_original'].notna().sum()
    assert valid_predictions > 0, "Model should produce some valid predictions despite NaNs"
    
    # Verify metrics can be computed on non-NaN subset
    valid_mask = grid['model_original'].notna() & grid['rain_truth'].notna()
    if valid_mask.sum() > 0:
        truth_bool = grid.loc[valid_mask, 'rain_truth'] == 1.0
        conf = rl.confusion_at_threshold(
            grid.loc[valid_mask, 'model_original'],
            truth_bool,
            threshold=50
        )
        assert conf['n'] > 0, "Should compute metrics on valid subset"


def test_pipeline_output_shapes_and_ranges(synthetic_ha_data, synthetic_openmeteo_data):
    """
    Validate output shapes and value ranges throughout the pipeline.
    
    Ensures:
    - Grid length matches expected sample count
    - Feature columns have correct dtypes
    - Model outputs are properly bounded
    - Metric values are in valid ranges
    """
    om_df = rl.load_open_meteo(synthetic_openmeteo_data)
    grid = rl.build_grid(
        ha_wide_df=synthetic_ha_data,
        om_df=om_df,
    )
    
    original_length = len(grid)
    
    grid['rain_truth'] = rl.label_rain(grid, precip_col='om_precip', threshold_mm=0.1)
    
    assert len(grid) == original_length, "label_rain should not change grid length"
    
    # Compute features
    grid['spread'] = rl.dew_point_spread(grid['temp'], grid['rh'])
    grid['spread_deriv'] = rl.derivative(grid['spread'], window='3h')
    
    # Validate feature dtypes and ranges
    assert grid['temp'].dtype in [np.float64, np.float32], "temp should be float"
    assert grid['rh'].dtype in [np.float64, np.float32], "rh should be float"
    assert grid['spread'].dtype in [np.float64, np.float32], "spread should be float"
    
    # Validate physical constraints
    valid_temp = grid['temp'].dropna()
    if len(valid_temp) > 0:
        assert (valid_temp > -50).all(), "Temperature should be > -50°C"
        assert (valid_temp < 50).all(), "Temperature should be < 50°C"
    
    valid_rh = grid['rh'].dropna()
    if len(valid_rh) > 0:
        assert (valid_rh >= 0).all(), "RH should be >= 0%"
        assert (valid_rh <= 100).all(), "RH should be <= 100%"
    
    # Run model and validate output shape
    params = ModelParams()
    ctx = ModelContext(
        spread=grid['spread'],
        spread_deriv=grid['spread_deriv'],
        abs_humidity=grid.get('abs_humidity'),
        temp=grid.get('temp'),
        pressure=grid.get('pressure'),
    )
    
    grid['model_test'] = rl.model_original(ctx, params)
    
    assert len(grid['model_test']) == original_length, "Model output should match grid length"
    
    # Validate metric ranges
    valid_mask = grid['model_test'].notna() & grid['rain_truth'].notna()
    if valid_mask.sum() > 0:
        truth_bool = grid.loc[valid_mask, 'rain_truth'] == 1.0
        sweep = rl.sweep_threshold(
            grid.loc[valid_mask, 'model_test'],
            truth_bool
        )
        
        # Check that precision/recall are in [0, 1]
        valid_precision = sweep['precision'].dropna()
        valid_recall = sweep['recall'].dropna()
        
        if len(valid_precision) > 0:
            assert (valid_precision >= 0).all(), "Precision should be >= 0"
            assert (valid_precision <= 1).all(), "Precision should be <= 1"
        
        if len(valid_recall) > 0:
            assert (valid_recall >= 0).all(), "Recall should be >= 0"
            assert (valid_recall <= 1).all(), "Recall should be <= 1"


def test_pipeline_metric_monotonicity(synthetic_ha_data, synthetic_openmeteo_data):
    """
    Verify expected monotonicity in threshold sweep.
    
    As threshold increases:
    - Precision should generally increase (fewer false positives)
    - Recall should generally decrease (more false negatives)
    
    Note: Not strictly monotonic due to discrete data, but trends should hold.
    """
    om_df = rl.load_open_meteo(synthetic_openmeteo_data)
    grid = rl.build_grid(
        ha_wide_df=synthetic_ha_data,
        om_df=om_df,
    )
    
    grid['rain_truth'] = rl.label_rain(grid, precip_col='om_precip', threshold_mm=0.1)
    
    grid['spread'] = rl.dew_point_spread(grid['temp'], grid['rh'])
    grid['spread_deriv'] = rl.derivative(grid['spread'], window='3h')
    
    params = ModelParams()
    ctx = ModelContext(
        spread=grid['spread'],
        spread_deriv=grid['spread_deriv'],
        abs_humidity=grid.get('abs_humidity'),
        temp=grid.get('temp'),
        pressure=grid.get('pressure'),
    )
    
    grid['model_test'] = rl.model_original(ctx, params)
    
    valid_mask = grid['model_test'].notna() & grid['rain_truth'].notna()
    
    if valid_mask.sum() > 0:
        truth_bool = grid.loc[valid_mask, 'rain_truth'] == 1.0
        sweep = rl.sweep_threshold(
            grid.loc[valid_mask, 'model_test'],
            truth_bool
        )
        
        # Check that recall is non-increasing (allowing for small violations)
        recall_values = sweep['recall'].dropna().values
        if len(recall_values) > 1:
            # Count decreases vs increases
            decreases = sum(recall_values[i] >= recall_values[i+1] for i in range(len(recall_values)-1))
            increases = len(recall_values) - 1 - decreases
            
            # Recall should decrease more often than increase
            assert decreases >= increases, \
                "Recall should generally decrease as threshold increases"


def test_pipeline_zero_rain(synthetic_ha_data, tmp_path):
    """
    Pipeline with zero rain in ground truth.
    
    Verifies graceful handling when no rain events occur:
    - Label stats report zero rain hours
    - Metrics handle all-negative ground truth
    - Threshold recommendation doesn't crash
    """
    # Create OpenMeteo data with no rain
    base_time = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    times = [base_time + timedelta(hours=i) for i in range(10)]
    
    json_path = tmp_path / "openmeteo_no_rain.json"
    import json
    with open(json_path, 'w') as f:
        json.dump({
            "latitude": 50.0,
            "longitude": 30.0,
            "utc_offset_seconds": 0,
            "hourly": {
                "time": [t.strftime("%Y-%m-%dT%H:%M") for t in times],
                "temperature_2m": [20.0] * 10,
                "precipitation": [0.0] * 10,  # No rain
            }
        }, f)
    
    # Build grid and label
    om_df = rl.load_open_meteo(str(json_path))
    grid = rl.build_grid(
        ha_wide_df=synthetic_ha_data,
        om_df=om_df,
    )
    
    grid['rain_truth'] = rl.label_rain(grid, precip_col='om_precip', threshold_mm=0.1)
    
    rain_hours = (grid['rain_truth'] == 1.0).sum()
    no_rain_hours = (grid['rain_truth'] == 0.0).sum()
    
    assert rain_hours == 0, "Should report zero rain hours"
    assert no_rain_hours > 0, "Should report all hours as no-rain"
    
    # Run model
    grid['spread'] = rl.dew_point_spread(grid['temp'], grid['rh'])
    grid['spread_deriv'] = rl.derivative(grid['spread'], window='3h')
    
    params = ModelParams()
    ctx = ModelContext(
        spread=grid['spread'],
        spread_deriv=grid['spread_deriv'],
        abs_humidity=grid.get('abs_humidity'),
        temp=grid.get('temp'),
        pressure=grid.get('pressure'),
    )
    
    grid['model_test'] = rl.model_original(ctx, params)
    
    # Metrics should handle all-negative case
    valid_mask = grid['model_test'].notna() & grid['rain_truth'].notna()
    if valid_mask.sum() > 0:
        truth_bool = grid.loc[valid_mask, 'rain_truth'] == 1.0
        conf = rl.confusion_at_threshold(
            grid.loc[valid_mask, 'model_test'],
            truth_bool,
            threshold=50
        )
        
        # With no positive labels, tp and fn should be 0
        assert conf['tp'] == 0, "True positives should be 0 with no rain"
        assert conf['fn'] == 0, "False negatives should be 0 with no rain"
        assert conf['n'] > 0, "Should still have samples"


def test_pipeline_all_rain(synthetic_ha_data, tmp_path):
    """
    Pipeline with all hours labeled as rain.
    
    Verifies handling of all-positive ground truth:
    - Label stats report all hours as rain
    - Metrics handle all-positive case
    """
    # Create OpenMeteo data with constant rain
    base_time = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    times = [base_time + timedelta(hours=i) for i in range(10)]
    
    json_path = tmp_path / "openmeteo_all_rain.json"
    import json
    with open(json_path, 'w') as f:
        json.dump({
            "latitude": 50.0,
            "longitude": 30.0,
            "utc_offset_seconds": 0,
            "hourly": {
                "time": [t.strftime("%Y-%m-%dT%H:%M") for t in times],
                "temperature_2m": [20.0] * 10,
                "precipitation": [1.0] * 10,  # Constant rain
            }
        }, f)
    
    # Build grid and label
    om_df = rl.load_open_meteo(str(json_path))
    grid = rl.build_grid(
        ha_wide_df=synthetic_ha_data,
        om_df=om_df,
    )
    
    grid['rain_truth'] = rl.label_rain(grid, precip_col='om_precip', threshold_mm=0.1)
    
    rain_hours = (grid['rain_truth'] == 1.0).sum()
    no_rain_hours = (grid['rain_truth'] == 0.0).sum()
    
    assert rain_hours > 0, "Should report all hours as rain"
    assert no_rain_hours == 0, "Should report zero no-rain hours"
    
    # Run model
    grid['spread'] = rl.dew_point_spread(grid['temp'], grid['rh'])
    grid['spread_deriv'] = rl.derivative(grid['spread'], window='3h')
    
    params = ModelParams()
    ctx = ModelContext(
        spread=grid['spread'],
        spread_deriv=grid['spread_deriv'],
        abs_humidity=grid.get('abs_humidity'),
        temp=grid.get('temp'),
        pressure=grid.get('pressure'),
    )
    
    grid['model_test'] = rl.model_original(ctx, params)
    
    # Metrics should handle all-positive case
    valid_mask = grid['model_test'].notna() & grid['rain_truth'].notna()
    if valid_mask.sum() > 0:
        truth_bool = grid.loc[valid_mask, 'rain_truth'] == 1.0
        conf = rl.confusion_at_threshold(
            grid.loc[valid_mask, 'model_test'],
            truth_bool,
            threshold=50
        )
        
        # With all positive labels, tn and fp should be 0
        assert conf['tn'] == 0, "True negatives should be 0 with all rain"
        assert conf['fp'] == 0, "False positives should be 0 with all rain"
        assert conf['n'] > 0, "Should still have samples"
