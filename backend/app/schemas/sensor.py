from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional
from .base import IDMixin, TimestampMixin


class SensorBase(BaseModel):
    """Base schema for Sensor."""
    name: str = Field(..., min_length=1, max_length=100)
    unit: Optional[str] = Field(None, max_length=20)
    sensor_type: str = Field(default="numeric", pattern="^(numeric|boolean|text)$")
    description: Optional[str] = None


class SensorCreate(SensorBase):
    """Schema for creating a new Sensor."""
    pass


class SensorUpdate(BaseModel):
    """Schema for updating a Sensor."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    unit: Optional[str] = Field(None, max_length=20)
    sensor_type: Optional[str] = Field(None, pattern="^(numeric|boolean|text)$")
    description: Optional[str] = None


class SensorResponse(SensorBase, IDMixin, TimestampMixin):
    """Schema for Sensor response."""
    model_config = ConfigDict(from_attributes=True)
