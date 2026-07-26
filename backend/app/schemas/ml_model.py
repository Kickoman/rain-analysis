from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional
from .base import IDMixin, TimestampMixin


class MLModelBase(BaseModel):
    """Base schema for MLModel."""
    name: str = Field(..., min_length=1, max_length=100)
    version: str = Field(..., max_length=50)
    model_type: str = Field(..., max_length=50)
    description: Optional[str] = None
    model_path: Optional[str] = Field(None, max_length=255)
    is_active: bool = Field(default=True)


class MLModelCreate(MLModelBase):
    """Schema for creating a new MLModel."""
    pass


class MLModelUpdate(BaseModel):
    """Schema for updating an MLModel."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    version: Optional[str] = Field(None, max_length=50)
    model_type: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None
    model_path: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None


class MLModelResponse(MLModelBase, IDMixin, TimestampMixin):
    """Schema for MLModel response."""
    model_config = ConfigDict(from_attributes=True)
