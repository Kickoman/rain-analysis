"""Tests for health check endpoints."""
import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from unittest.mock import AsyncMock
import time


@pytest.mark.asyncio
async def test_health_check_success(client: AsyncClient):
    """Test health check endpoint returns healthy when database is available."""
    response = await client.get("/health")
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    
    assert data["status"] == "healthy"
    assert "checks" in data
    assert data["checks"]["api"] == "ok"
    assert data["checks"]["database"] == "ok"
    assert data["checks"]["version"] == "0.1.0"
    assert "uptime_seconds" in data["checks"]
    assert "database_latency_ms" in data["checks"]
    assert data["checks"]["database_latency_ms"] >= 0


@pytest.mark.asyncio
async def test_health_check_database_failure(app, client: AsyncClient):
    """Test health check returns 503 when database is unavailable."""
    from app.database import get_db
    
    # Mock failing database
    async def mock_failing_db():
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute = AsyncMock(side_effect=Exception("Database connection failed"))
        yield mock_session
    
    # Override dependency
    app.dependency_overrides[get_db] = mock_failing_db
    
    try:
        response = await client.get("/health")
        
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        data = response.json()
        
        assert data["status"] == "unhealthy"
        assert data["checks"]["database"] == "error"
        assert "database_error" in data["checks"]
        assert "Database connection failed" in data["checks"]["database_error"]
    finally:
        # Clean up override
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_check_includes_uptime(client: AsyncClient):
    """Test health check includes uptime in seconds."""
    response = await client.get("/health")
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    
    assert "uptime_seconds" in data["checks"]
    assert isinstance(data["checks"]["uptime_seconds"], int)
    assert data["checks"]["uptime_seconds"] >= 0


@pytest.mark.asyncio
async def test_liveness_check(client: AsyncClient):
    """Test liveness probe always returns alive."""
    response = await client.get("/health/live")
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    
    assert data["status"] == "alive"


@pytest.mark.asyncio
async def test_liveness_check_no_database_dependency(client: AsyncClient):
    """Test liveness probe works even if database is down."""
    # Liveness check should not depend on database
    # It should always return 200 as long as the process is running
    response = await client.get("/health/live")
    
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_readiness_check_success(client: AsyncClient):
    """Test readiness probe returns ready when database is available."""
    response = await client.get("/health/ready")
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    
    assert data["status"] == "ready"


@pytest.mark.asyncio
async def test_readiness_check_database_failure(app, client: AsyncClient):
    """Test readiness probe returns 503 when database is unavailable."""
    from app.database import get_db
    
    async def mock_failing_db():
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute = AsyncMock(side_effect=Exception("Database unavailable"))
        yield mock_session
    
    app.dependency_overrides[get_db] = mock_failing_db
    
    try:
        response = await client.get("/health/ready")
        
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        data = response.json()
        
        assert data["status"] == "not_ready"
        assert data["reason"] == "database_unavailable"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_check_latency_measurement(client: AsyncClient):
    """Test health check measures database query latency."""
    response = await client.get("/health")
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    
    # Latency should be measured in milliseconds
    assert "database_latency_ms" in data["checks"]
    latency = data["checks"]["database_latency_ms"]
    
    # Latency should be a positive number (even if very small)
    assert isinstance(latency, int)
    assert latency >= 0
    
    # Sanity check: latency should be less than 1 second for simple SELECT 1
    assert latency < 1000


@pytest.mark.asyncio
async def test_health_endpoints_no_authentication(client: AsyncClient):
    """Test that health endpoints don't require authentication."""
    # All health endpoints should be accessible without X-API-Key header
    endpoints = ["/health", "/health/live", "/health/ready"]
    
    for endpoint in endpoints:
        response = await client.get(endpoint)
        # Should not return 401 Unauthorized
        assert response.status_code != status.HTTP_401_UNAUTHORIZED
