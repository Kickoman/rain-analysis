"""Authentication and rate limiting middleware."""

from datetime import datetime, timezone

from fastapi import Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from ..constants import EXEMPT_PATHS
from ..models.api_key import APIKey
from ..models.api_request_log import APIRequestLog
from .crypto import hash_api_key
from .rate_limiter import InMemoryRateLimiter
from ..database import AsyncSessionLocal
import logging
import traceback

logger = logging.getLogger(__name__)

# Global rate limiter instance
rate_limiter = InMemoryRateLimiter()


async def auth_middleware(request: Request, call_next):
    """
    Authentication and rate limiting middleware.

    Checks API key validity, applies rate limits, and logs requests.
    """
    # Skip auth for the root/info page, health probes, and docs
    if request.url.path in EXEMPT_PATHS:
        return await call_next(request)

    # Extract API key from header
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Missing API key"},
        )

    # Verify API key
    async with AsyncSessionLocal() as db:
        try:
            # Compute hash once - O(1)
            api_key_hash = hash_api_key(api_key)

            # Direct indexed lookup - O(1) instead of loading all keys
            result = await db.execute(
                select(APIKey).where(
                    APIKey.key_hash == api_key_hash,
                    APIKey.is_active == True
                )
            )
            api_key_obj = result.scalar_one_or_none()

            if not api_key_obj:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Invalid API key"},
                )

            if api_key_obj.expires_at is not None:
                expires_at = api_key_obj.expires_at
                # SQLite returns naive datetimes; the column semantics are UTC
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at < datetime.now(timezone.utc):
                    return JSONResponse(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        content={"detail": "API key expired"},
                    )

            # Check rate limits
            allowed = await rate_limiter.check_rate_limit(
                api_key_obj.id,
                api_key_obj.rate_limit_rpm,
                api_key_obj.rate_limit_rph,
                api_key_obj.rate_limit_rpd,
            )

            if not allowed:
                # Log rate-limited request (wrapped in try-except to not fail the response)
                try:
                    log_entry = APIRequestLog(
                        api_key_id=api_key_obj.id,
                        endpoint=request.url.path,
                        method=request.method,
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        ip_address=request.client.host if request.client else None,
                        user_agent=request.headers.get("user-agent"),
                    )
                    db.add(log_entry)
                    await db.commit()
                except Exception as log_error:
                    logger.warning(
                        f"Failed to log rate-limited request: {log_error}",
                        exc_info=True
                    )

                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Rate limit exceeded"},
                )

            # Store key info in request state
            request.state.api_key = api_key_obj

            # Process request
            response = await call_next(request)

            # Log successful request (wrapped in try-except to not fail the response)
            try:
                log_entry = APIRequestLog(
                    api_key_id=api_key_obj.id,
                    endpoint=request.url.path,
                    method=request.method,
                    status_code=response.status_code,
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                )
                db.add(log_entry)
                # Piggyback last_used_at on the request-log commit
                api_key_obj.last_used_at = datetime.now(timezone.utc)
                db.add(api_key_obj)
                await db.commit()
            except Exception as log_error:
                logger.warning(
                    f"Failed to log request: {log_error}",
                    exc_info=True
                )

            return response

        except OperationalError as e:
            # Database connection issues - service unavailable
            logger.error(
                f"Database connection failed in auth middleware: {e}",
                exc_info=True,
                extra={
                    "error_type": "OperationalError",
                    "endpoint": request.url.path,
                    "method": request.method,
                }
            )
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"detail": "Database service unavailable"},
            )

        except SQLAlchemyError as e:
            # Other database errors - provide details for debugging
            logger.error(
                f"Database error in auth middleware: {e}",
                exc_info=True,
                extra={
                    "error_type": type(e).__name__,
                    "endpoint": request.url.path,
                    "method": request.method,
                }
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Database error"},
            )

        except Exception as e:
            # Unexpected errors - log full traceback
            logger.error(
                f"Unexpected error in auth middleware: {e}",
                exc_info=True,
                extra={
                    "error_type": type(e).__name__,
                    "endpoint": request.url.path,
                    "method": request.method,
                    "traceback": traceback.format_exc(),
                }
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Internal server error"},
            )
