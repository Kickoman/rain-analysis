from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional


class TimestampMixin(BaseModel):
    """Mixin for models with created_at timestamp."""
    created_at: datetime


class IDMixin(BaseModel):
    """Mixin for models with ID field."""
    id: int
