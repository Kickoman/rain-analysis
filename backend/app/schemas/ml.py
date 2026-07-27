"""
Pydantic schemas for ML-related API requests and responses.
"""

from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import List, Dict, Any, Optional


# Model schemas
class MLModelBase(BaseModel):
    """Base schema for ML models."""
    name: str = Field(..., max_length=100)
    version: Optional[str] = Field(None, max_length=20)
    description: Optional[str] = Field(None, max_length=500)
    config: Dict[str, Any] = Field(default_factory=dict)
    active: bool = True


class MLModelCreate(MLModelBase):
    """Schema for creating a new ML model."""
    pass


class MLModelUpdate(BaseModel):
    """Schema for updating an ML model."""
    version: Optional[str] = None
    description: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    active: Optional[bool] = None


class MLModelResponse(MLModelBase):
    """Schema for ML model response."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    created_at: datetime


class MLModelListResponse(BaseModel):
    """Schema for list of ML models."""
    models: List[MLModelResponse]


# Prediction schemas
class PredictionResponse(BaseModel):
    """Schema for a single prediction result."""
    model_config = ConfigDict(from_attributes=True)
    
    model: str
    probability: float
    binary_prediction: bool
    threshold: float


class CurrentPredictionsResponse(BaseModel):
    """Schema for current predictions from all active models."""
    timestamp: datetime
    predictions: List[PredictionResponse]


class PredictionHistoryItem(BaseModel):
    """Schema for a single prediction history data point."""
    timestamp: datetime
    probability: float
    binary_prediction: bool


class PredictionHistoryResponse(BaseModel):
    """Schema for prediction history for a specific model."""
    model: str
    data: List[PredictionHistoryItem]


class EvaluationDataPoint(BaseModel):
    """Schema for a single data point in evaluation request."""
    timestamp: datetime
    temperature: float
    humidity: float
    pressure: Optional[float] = None
    wind_speed: Optional[float] = None
    # Add other features as needed


class EvaluationRequest(BaseModel):
    """Schema for model evaluation request."""
    model: str
    data: List[EvaluationDataPoint]


class EvaluationPrediction(BaseModel):
    """Schema for a single evaluation prediction result."""
    timestamp: datetime
    probability: float


class EvaluationResponse(BaseModel):
    """Schema for model evaluation response."""
    predictions: List[EvaluationPrediction]


# Metrics schemas
class ConfusionMatrix(BaseModel):
    """Schema for confusion matrix."""
    TP: int
    FP: int
    FN: int
    TN: int


class ModelMetricsResponse(BaseModel):
    """Schema for model metrics response."""
    model_config = ConfigDict(from_attributes=True)
    
    date: datetime
    brier_score: Optional[float] = None
    f1_score: Optional[float] = None
    f2_score: Optional[float] = None
    precision_score: Optional[float] = None
    recall: Optional[float] = None
    calibration_slope: Optional[float] = None
    threshold: Optional[float] = None
    confusion_matrix: Optional[ConfusionMatrix] = None


class LatestMetricsResponse(BaseModel):
    """Schema for latest metrics for a specific model."""
    model: str
    latest_metrics: ModelMetricsResponse


class MetricsHistoryResponse(BaseModel):
    """Schema for metrics history for a specific model."""
    model: str
    history: List[ModelMetricsResponse]
