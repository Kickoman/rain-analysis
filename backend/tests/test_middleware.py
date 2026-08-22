"""Tests for authentication middleware."""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from unittest.mock import AsyncMock, patch, MagicMock
from app.auth.middleware import auth_middleware, rate_limiter
from app.auth.crypto import hash_api_key
from app.models.api_key import APIKey
from app.models.api_request_log import APIRequestLog
from app.database import AsyncSessionLocal, Base, engine
import secrets


# Test app setup
app = FastAPI()
app.middleware("http")(auth_middleware)


@app.get("/test")
async def test_endpoint():
    """Test endpoint that requires authentication."""
    return {"message": "success"}


@app.get("/health")
async def health_endpoint():
    """Health check endpoint that bypasses auth."""
    return {"status": "ok"}


@pytest.fixture
async def setup_database():
    """Setup test database."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def test_api_key(setup_database):
    """Create a test API key."""
    raw_key = secrets.token_urlsafe(32)
    key_hash = hash_api_key(raw_key)
    key_prefix = raw_key[:16]
    
    async with AsyncSessionLocal() as db:
        api_key = APIKey(
            key_hash=key_hash,
            key_prefix=key_prefix,
            owner="test_owner",
            description="Test API key",
            scope="read",
            rate_limit_rpm=10,
            rate_limit_rph=100,
            rate_limit_rpd=1000,
            is_active=True,
        )
        db.add(api_key)
        await db.commit()
        await db.refresh(api_key)
        
        yield raw_key, api_key.id


@pytest.mark.asyncio
async def test_middleware_allows_health_check_without_auth():
    """Test that health check endpoint bypasses authentication."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_middleware_rejects_missing_api_key(setup_database):
    """Test that requests without API key are rejected."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/test")
        assert response.status_code == 401
        assert response.json() == {"detail": "Missing API key"}


@pytest.mark.asyncio
async def test_middleware_rejects_invalid_api_key(setup_database):
    """Test that requests with invalid API key are rejected."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(
            "/test",
            headers={"X-API-Key": "invalid_key_12345"}
        )
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid API key"}


@pytest.mark.asyncio
async def test_middleware_allows_valid_api_key(test_api_key):
    """Test that requests with valid API key are allowed."""
    raw_key, key_id = test_api_key
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(
            "/test",
            headers={"X-API-Key": raw_key}
        )
        assert response.status_code == 200
        assert response.json() == {"message": "success"}


@pytest.mark.asyncio
async def test_middleware_logs_requests(test_api_key):
    """Test that middleware logs API requests."""
    raw_key, key_id = test_api_key
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        await client.get(
            "/test",
            headers={"X-API-Key": raw_key}
        )
    
    # Check that request was logged
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(APIRequestLog).where(APIRequestLog.api_key_id == key_id)
        )
        logs = result.scalars().all()
        
        assert len(logs) == 1
        log = logs[0]
        assert log.endpoint == "/test"
        assert log.method == "GET"
        assert log.status_code == 200


@pytest.mark.asyncio
async def test_middleware_enforces_rate_limits(test_api_key):
    """Test that middleware enforces rate limits."""
    raw_key, key_id = test_api_key
    
    # Clear any existing rate limit state
    rate_limiter._counters.clear()
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Make 10 requests (at RPM limit)
        for i in range(10):
            response = await client.get(
                "/test",
                headers={"X-API-Key": raw_key}
            )
            assert response.status_code == 200, f"Request {i+1} should succeed"
        
        # 11th request should be rate limited
        response = await client.get(
            "/test",
            headers={"X-API-Key": raw_key}
        )
        assert response.status_code == 429
        assert response.json() == {"detail": "Rate limit exceeded"}


@pytest.mark.asyncio
async def test_middleware_logs_rate_limited_requests(test_api_key):
    """Test that rate-limited requests are logged."""
    raw_key, key_id = test_api_key
    
    # Clear rate limit state
    rate_limiter._counters.clear()
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Exhaust rate limit
        for _ in range(10):
            await client.get("/test", headers={"X-API-Key": raw_key})
        
        # Make rate-limited request
        await client.get("/test", headers={"X-API-Key": raw_key})
    
    # Check that rate-limited request was logged
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(APIRequestLog)
            .where(APIRequestLog.api_key_id == key_id)
            .where(APIRequestLog.status_code == 429)
        )
        logs = result.scalars().all()
        
        assert len(logs) >= 1
        log = logs[0]
        assert log.status_code == 429


@pytest.mark.asyncio
async def test_middleware_handles_inactive_key(setup_database):
    """Test that inactive API keys are rejected."""
    raw_key = secrets.token_urlsafe(32)
    key_hash = hash_api_key(raw_key)
    key_prefix = raw_key[:16]
    
    async with AsyncSessionLocal() as db:
        api_key = APIKey(
            key_hash=key_hash,
            key_prefix=key_prefix,
            owner="test_owner",
            description="Inactive API key",
            scope="read",
            is_active=False,  # Inactive
        )
        db.add(api_key)
        await db.commit()
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(
            "/test",
            headers={"X-API-Key": raw_key}
        )
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid API key"}


@pytest.mark.asyncio
async def test_middleware_handles_operational_error(test_api_key):
    """Test that OperationalError returns 503 Service Unavailable."""
    raw_key, key_id = test_api_key
    
    # Mock database execute to raise OperationalError
    with patch('app.auth.middleware.AsyncSessionLocal') as mock_session:
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=OperationalError("Connection failed", None, None))
        mock_session.return_value.__aenter__.return_value = mock_db
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get(
                "/test",
                headers={"X-API-Key": raw_key}
            )
            assert response.status_code == 503
            assert response.json() == {"detail": "Database service unavailable"}


@pytest.mark.asyncio
async def test_middleware_handles_sqlalchemy_error(test_api_key):
    """Test that SQLAlchemyError returns 500 with error type."""
    raw_key, key_id = test_api_key
    
    # Mock database execute to raise generic SQLAlchemyError
    with patch('app.auth.middleware.AsyncSessionLocal') as mock_session:
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=SQLAlchemyError("Database error"))
        mock_session.return_value.__aenter__.return_value = mock_db
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get(
                "/test",
                headers={"X-API-Key": raw_key}
            )
            assert response.status_code == 500
            assert "Database error" in response.json()["detail"]


@pytest.mark.asyncio
async def test_middleware_handles_unexpected_exception(test_api_key):
    """Test that unexpected exceptions are logged with full traceback."""
    raw_key, key_id = test_api_key
    
    # Mock database execute to raise unexpected exception
    with patch('app.auth.middleware.AsyncSessionLocal') as mock_session:
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=RuntimeError("Unexpected error"))
        mock_session.return_value.__aenter__.return_value = mock_db
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get(
                "/test",
                headers={"X-API-Key": raw_key}
            )
            assert response.status_code == 500
            assert response.json() == {"detail": "Internal server error"}


@pytest.mark.asyncio
async def test_middleware_continues_on_logging_failure(test_api_key):
    """Test that request succeeds even if logging fails."""
    raw_key, key_id = test_api_key
    
    # Mock commit to fail (simulating logging failure)
    with patch('app.auth.middleware.AsyncSessionLocal') as mock_session:
        mock_db = AsyncMock()
        
        # First execute succeeds (for auth check)
        mock_result = MagicMock()
        
        # Setup real API key for auth
        async with AsyncSessionLocal() as real_db:
            result = await real_db.execute(select(APIKey).where(APIKey.id == key_id))
            real_key = result.scalars().first()
            mock_result.scalar_one_or_none.return_value = real_key
        
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        # Commit fails (logging failure)
        mock_db.commit = AsyncMock(side_effect=OperationalError("Log commit failed", None, None))
        mock_db.add = MagicMock()
        
        mock_session.return_value.__aenter__.return_value = mock_db
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get(
                "/test",
                headers={"X-API-Key": raw_key}
            )
            # Request should still succeed despite logging failure
            assert response.status_code == 200
            assert response.json() == {"message": "success"}
