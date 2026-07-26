"""
Pydantic schemas for API validation.
"""

from .base import IDMixin, TimestampMixin
from .sensor import SensorBase, SensorCreate, SensorUpdate, SensorResponse
from .measurement import (
    MeasurementBase,
    MeasurementCreate,
    MeasurementResponse,
    MeasurementBulkCreate,
)
from .ml_model import MLModelBase, MLModelCreate, MLModelUpdate, MLModelResponse
from .prediction import PredictionBase, PredictionCreate, PredictionResponse
from .model_metric import ModelMetricBase, ModelMetricCreate, ModelMetricResponse
from .common import PaginatedResponse, ErrorResponse

__all__ = [
    # Base mixins
    "IDMixin",
    "TimestampMixin",
    # Sensor schemas
    "SensorBase",
    "SensorCreate",
    "SensorUpdate",
    "SensorResponse",
    # Measurement schemas
    "MeasurementBase",
    "MeasurementCreate",
    "MeasurementResponse",
    "MeasurementBulkCreate",
    # ML Model schemas
    "MLModelBase",
    "MLModelCreate",
    "MLModelUpdate",
    "MLModelResponse",
    # Prediction schemas
    "PredictionBase",
    "PredictionCreate",
    "PredictionResponse",
    # Model Metric schemas
    "ModelMetricBase",
    "ModelMetricCreate",
    "ModelMetricResponse",
    # Common schemas
    "PaginatedResponse",
    "ErrorResponse",
]
