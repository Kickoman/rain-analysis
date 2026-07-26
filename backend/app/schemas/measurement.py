from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional, Any
from .base import IDMixin


class MeasurementBase(BaseModel):
    """Base schema for Measurement."""
    sensor_id: int
    timestamp: datetime
    value: Any
    source: str = Field(default="manual", max_length=50)


class MeasurementCreate(MeasurementBase):
    """Schema for creating a new Measurement."""
    pass


class MeasurementResponse(MeasurementBase, IDMixin):
    """Schema for Measurement response."""
    model_config = ConfigDict(from_attributes=True)


class MeasurementBulkCreate(BaseModel):
    """Schema for bulk creating Measurements."""
    measurements: list[MeasurementCreate]
