"""Authentication and rate limiting middleware."""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from app.models.api_key import APIKey
from app.models.api_request_log import APIRequestLog
from app.auth.crypto import verify_api_key
from app.auth.rate_limiter import InMemoryRateLimiter
from app.database import AsyncSessionLocal
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
    # Skip auth for health check and docs
    if request.url.path in ["/health", "/docs", "/openapi.json", "/redoc"]:
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
            result = await db.execute(select(APIKey).where(APIKey.is_active == True))
            keys = result.scalars().all()

            api_key_obj = None
            for key in keys:
                if verify_api_key(api_key, key.key_hash):
                    api_key_obj = key
                    break

            if not api_key_obj:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Invalid API key"},
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
                content={"detail": f"Database error: {type(e).__name__}"},
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
