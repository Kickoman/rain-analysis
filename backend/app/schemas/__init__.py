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
from .api_key import (
    APIKeyCreate,
    APIKeyResponse,
    APIKeyCreateResponse,
    APIKeyUpdate,
)
from .common import PaginatedResponse, ErrorResponse
from .ml import (
    MLModelResponse,
    MLModelListResponse,
    MLModelCreate,
    MLModelUpdate,
    CurrentPredictionsResponse,
    PredictionResponse,
    PredictionHistoryResponse,
    EvaluationRequest,
    EvaluationResponse,
    LatestMetricsResponse,
    MetricsHistoryResponse,
)

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
    # API Key schemas
    "APIKeyCreate",
    "APIKeyResponse",
    "APIKeyCreateResponse",
    "APIKeyUpdate",
    # Common schemas
    "PaginatedResponse",
    "ErrorResponse",
    # ML endpoint schemas
    "MLModelResponse",
    "MLModelListResponse",
    "MLModelCreate",
    "MLModelUpdate",
    "CurrentPredictionsResponse",
    "PredictionResponse",
    "PredictionHistoryResponse",
    "EvaluationRequest",
    "EvaluationResponse",
    "LatestMetricsResponse",
    "MetricsHistoryResponse",
]
