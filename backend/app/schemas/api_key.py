"""Pydantic schemas for API key management."""
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional


class APIKeyCreate(BaseModel):
    """Schema for creating a new API key."""

    owner: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    scope: str = Field(..., pattern="^(read|write|admin)$")
    rate_limit_rpm: Optional[int] = Field(None, ge=1)
    rate_limit_rph: Optional[int] = Field(None, ge=1)
    rate_limit_rpd: Optional[int] = Field(None, ge=1)
    environment: str = Field("live", pattern="^(live|test)$")
    expires_at: Optional[datetime] = None


class APIKeyResponse(BaseModel):
    """Schema for API key response (without the actual key)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    key_prefix: str
    owner: Optional[str]
    description: Optional[str]
    scope: str
    rate_limit_rpm: Optional[int]
    rate_limit_rph: Optional[int]
    rate_limit_rpd: Optional[int]
    is_active: bool
    created_at: datetime
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]


class APIKeyCreateResponse(BaseModel):
    """Schema for API key creation response (includes full key, shown only once)."""

    key: str  # Full key, only shown once
    key_info: APIKeyResponse


class APIKeyUpdate(BaseModel):
    """Schema for updating API key limits or status."""

    rate_limit_rpm: Optional[int] = Field(None, ge=1)
    rate_limit_rph: Optional[int] = Field(None, ge=1)
    rate_limit_rpd: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None
