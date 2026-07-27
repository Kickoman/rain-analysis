"""Shared rain prediction library.

This package provides the core rain prediction models and utilities
used by both the analysis scripts and the backend API.

Import from this package instead of duplicating code:
    from rainlib import dew_point, derivative, ModelParams, ModelContext
    from rainlib.models import model_pressure_aware, MODELS
"""

# Re-export main module contents for convenience
from analysis.rainlib import (
    # Physics primitives
    MAGNUS_A,
    MAGNUS_B,
    dew_point,
    dew_point_spread,
    absolute_humidity,
    humidex,
    
    # Derivative
    derivative,
    
    # Pressure series builders
    build_pressure_series,
    build_pressure_series_ha,
    build_pressure_series_meteostat,
    build_pressure_series_yandex,
    build_pressure_series_legacy,
    
    # Model infrastructure
    ModelParams,
    ModelContext,
    
    # Models
    model_original,
    model_tuned,
    model_trend_dominant,
    model_ha_live,
    model_pressure_aware,
    MODELS,
    
    # Data loaders
    load_ha_csv,
    ha_wide,
    load_open_meteo,
    load_yandex_archive,
    load_meteostat,
    
    # Grid building
    PRECIP_COLUMNS,
    YX_STATE_COLUMNS,
    build_grid,
    label_rain,
    
    # Metrics
    confusion_at_threshold,
    sweep_threshold,
    lead_time,
    fbeta_at_threshold,
    recommend_threshold,
    plot_calibration,
)

__all__ = [
    # Physics
    "MAGNUS_A",
    "MAGNUS_B",
    "dew_point",
    "dew_point_spread",
    "absolute_humidity",
    "humidex",
    
    # Derivative
    "derivative",
    
    # Pressure
    "build_pressure_series",
    "build_pressure_series_ha",
    "build_pressure_series_meteostat",
    "build_pressure_series_yandex",
    "build_pressure_series_legacy",
    
    # Models
    "ModelParams",
    "ModelContext",
    "model_original",
    "model_tuned",
    "model_trend_dominant",
    "model_ha_live",
    "model_pressure_aware",
    "MODELS",
    
    # Data
    "load_ha_csv",
    "ha_wide",
    "load_open_meteo",
    "load_yandex_archive",
    "load_meteostat",
    
    # Grid
    "PRECIP_COLUMNS",
    "YX_STATE_COLUMNS",
    "build_grid",
    "label_rain",
    
    # Metrics
    "confusion_at_threshold",
    "sweep_threshold",
    "lead_time",
    "fbeta_at_threshold",
    "recommend_threshold",
    "plot_calibration",
]
