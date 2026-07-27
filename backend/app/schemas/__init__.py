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
from .api_key import (
    APIKeyCreate,
    APIKeyResponse,
    APIKeyCreateResponse,
    APIKeyUpdate,
)
from .common import PaginatedResponse, ErrorResponse
from .ml import (
    MLModelResponse as MLModelResponseV2,
    MLModelListResponse,
    MLModelCreate as MLModelCreateV2,
    MLModelUpdate as MLModelUpdateV2,
    CurrentPredictionsResponse,
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
    # ML Model schemas (legacy)
    "MLModelBase",
    "MLModelCreate",
    "MLModelUpdate",
    "MLModelResponse",
    # Prediction schemas (legacy)
    "PredictionBase",
    "PredictionCreate",
    "PredictionResponse",
    # Model Metric schemas (legacy)
    "ModelMetricBase",
    "ModelMetricCreate",
    "ModelMetricResponse",
    # API Key schemas
    "APIKeyCreate",
    "APIKeyResponse",
    "APIKeyCreateResponse",
    "APIKeyUpdate",
    # Common schemas
    "PaginatedResponse",
    "ErrorResponse",
    # ML endpoint schemas (new)
    "MLModelResponseV2",
    "MLModelListResponse",
    "MLModelCreateV2",
    "MLModelUpdateV2",
    "CurrentPredictionsResponse",
    "PredictionHistoryResponse",
    "EvaluationRequest",
    "EvaluationResponse",
    "LatestMetricsResponse",
    "MetricsHistoryResponse",
]
