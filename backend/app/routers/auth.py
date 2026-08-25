"""Public authentication endpoints."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..models import APIKey
from ..auth.middleware import rate_limiter
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthCheckResponse(BaseModel):
    """Response model for authentication check."""

    valid: bool
    key_id: int
    owner: str
    scope: str
    rate_limits: dict
    remaining: dict
    expires_at: Optional[datetime]


@router.get("/check", response_model=AuthCheckResponse)
async def check_auth(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Check API key validity and get rate limit info.

    This endpoint requires a valid API key in the Authorization header.
    Returns information about the key, its permissions, and remaining rate limits.

    Returns:
        AuthCheckResponse: API key information and rate limit status
    """
    # API key is validated by middleware and attached to request.state
    api_key: APIKey = request.state.api_key

    # Get remaining requests for each time window
    remaining = await rate_limiter.get_remaining(
        api_key.id,
        api_key.rate_limit_rpm or 0,
        api_key.rate_limit_rph or 0,
        api_key.rate_limit_rpd or 0
    )

    return AuthCheckResponse(
        valid=True,
        key_id=api_key.id,
        owner=api_key.owner,
        scope=api_key.scope,
        rate_limits={
            "rpm": api_key.rate_limit_rpm,
            "rph": api_key.rate_limit_rph,
            "rpd": api_key.rate_limit_rpd
        },
        remaining=remaining,
        expires_at=api_key.expires_at
    )
