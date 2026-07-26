from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional, Any
from .base import IDMixin, TimestampMixin


class PredictionBase(BaseModel):
    """Base schema for Prediction."""
    model_id: int
    prediction_time: datetime
    target_time: datetime
    predicted_value: Any
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    metadata: Optional[dict] = None


class PredictionCreate(PredictionBase):
    """Schema for creating a new Prediction."""
    pass


class PredictionResponse(PredictionBase, IDMixin, TimestampMixin):
    """Schema for Prediction response."""
    model_config = ConfigDict(from_attributes=True)
