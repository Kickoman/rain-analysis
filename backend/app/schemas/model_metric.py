from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional
from .base import IDMixin, TimestampMixin


class ModelMetricBase(BaseModel):
    """Base schema for ModelMetric."""
    model_id: int
    metric_name: str = Field(..., max_length=50)
    metric_value: float
    evaluation_date: datetime
    dataset_info: Optional[str] = Field(None, max_length=255)


class ModelMetricCreate(ModelMetricBase):
    """Schema for creating a new ModelMetric."""
    pass


class ModelMetricResponse(ModelMetricBase, IDMixin, TimestampMixin):
    """Schema for ModelMetric response."""
    model_config = ConfigDict(from_attributes=True)
