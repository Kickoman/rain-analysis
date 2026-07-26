"""Tests for public authentication endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta

from app.models import APIKey
from app.auth.crypto import generate_api_key


@pytest.fixture
async def test_api_key(db_session: AsyncSession) -> tuple[str, APIKey]:
    """Create a test API key."""
    full_key, key_hash, key_prefix = generate_api_key("test")
    
    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="test_owner",
        description="Test API key",
        scope="read",
        is_active=True
    )
    
    db_session.add(api_key)
    await db_session.commit()
    await db_session.refresh(api_key)
    
    return full_key, api_key


@pytest.mark.asyncio
async def test_auth_check_valid_key(client: AsyncClient, test_api_key):
    """Test /auth/check with valid API key."""
    raw_key, api_key = test_api_key
    
    response = await client.get(
        "/auth/check",
        headers={"X-API-Key": raw_key}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["owner"] == "test_owner"
    assert data["scope"] == "read"
    assert "rate_limits" in data
    assert "remaining" in data


@pytest.mark.asyncio
async def test_auth_check_with_rate_limits(client: AsyncClient, db_session: AsyncSession):
    """Test /auth/check returns correct rate limit information."""
    # Create API key with specific rate limits
    raw_key, key_hash, key_prefix = generate_api_key()
    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="rate_test",
        scope="read",
        rate_limit_rpm=10,
        rate_limit_rph=100,
        rate_limit_rpd=1000,
        is_active=True
    )
    db_session.add(api_key)
    await db_session.commit()

    response = await client.get(
        "/auth/check",
        headers={"X-API-Key": raw_key}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["rate_limits"]["rpm"] == 10
    assert data["rate_limits"]["rph"] == 100
    assert data["rate_limits"]["rpd"] == 1000
    # Middleware already counted this request, so remaining will be less than limit
    assert data["remaining"]["rpm_remaining"] < 10
    assert data["remaining"]["rph_remaining"] < 100
    assert data["remaining"]["rpd_remaining"] < 1000


@pytest.mark.asyncio
async def test_auth_check_with_expiration(client: AsyncClient, db_session: AsyncSession):
    """Test /auth/check returns expiration time."""
    # Create API key with expiration
    raw_key, key_hash, key_prefix = generate_api_key()
    expires_at = datetime.utcnow() + timedelta(days=30)
    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="expiry_test",
        scope="read",
        expires_at=expires_at,
        is_active=True
    )
    db_session.add(api_key)
    await db_session.commit()

    response = await client.get(
        "/auth/check",
        headers={"X-API-Key": raw_key}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["expires_at"] is not None
    # Parse and compare timestamps
    returned_time = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
    assert abs((returned_time - expires_at).total_seconds()) < 2


@pytest.mark.asyncio
async def test_auth_check_without_key(client: AsyncClient):
    """Test /auth/check without API key returns 401."""
    response = await client.get("/auth/check")

    assert response.status_code == 401
    data = response.json()
    assert "Missing API key" in data["detail"]


@pytest.mark.asyncio
async def test_auth_check_with_invalid_key(client: AsyncClient):
    """Test /auth/check with invalid API key returns 401."""
    response = await client.get(
        "/auth/check",
        headers={"X-API-Key": "invalid_key_12345"}
    )

    assert response.status_code == 401
    data = response.json()
    assert "Invalid API key" in data["detail"]


@pytest.mark.asyncio
async def test_auth_check_with_inactive_key(client: AsyncClient, db_session: AsyncSession):
    """Test /auth/check with inactive API key returns 401."""
    # Create inactive API key
    raw_key, key_hash, key_prefix = generate_api_key()
    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="inactive_test",
        scope="read",
        is_active=False  # Inactive
    )
    db_session.add(api_key)
    await db_session.commit()

    response = await client.get(
        "/auth/check",
        headers={"X-API-Key": raw_key}
    )

    assert response.status_code == 401
    data = response.json()
    assert "Invalid API key" in data["detail"]


@pytest.mark.asyncio
async def test_auth_check_remaining_decreases(client: AsyncClient, db_session: AsyncSession):
    """Test that remaining count decreases after requests."""
    # Create API key with higher rate limits to avoid hitting the limit
    raw_key, key_hash, key_prefix = generate_api_key()
    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="remaining_test",
        scope="read",
        rate_limit_rpm=50,  # Higher limit
        is_active=True
    )
    db_session.add(api_key)
    await db_session.commit()

    # First request
    response1 = await client.get(
        "/auth/check",
        headers={"X-API-Key": raw_key}
    )
    assert response1.status_code == 200
    data1 = response1.json()
    remaining1 = data1["remaining"]["rpm_remaining"]

    # Second request
    response2 = await client.get(
        "/auth/check",
        headers={"X-API-Key": raw_key}
    )
    assert response2.status_code == 200
    data2 = response2.json()
    remaining2 = data2["remaining"]["rpm_remaining"]

    # Remaining should decrease by 1
    assert remaining2 == remaining1 - 1


@pytest.mark.asyncio
async def test_auth_check_different_scopes(client: AsyncClient, db_session: AsyncSession):
    """Test /auth/check correctly reports different scopes."""
    for scope in ["read", "write", "admin"]:
        raw_key, key_hash, key_prefix = generate_api_key()
        api_key = APIKey(
            key_hash=key_hash,
            key_prefix=key_prefix,
            owner=f"{scope}_owner",
            scope=scope,
            is_active=True
        )
        db_session.add(api_key)
        await db_session.commit()

        response = await client.get(
            "/auth/check",
            headers={"X-API-Key": raw_key}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["scope"] == scope


@pytest.mark.asyncio
async def test_auth_check_null_rate_limits(client: AsyncClient, db_session: AsyncSession):
    """Test /auth/check with no rate limits (unlimited)."""
    raw_key, key_hash, key_prefix = generate_api_key()
    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="unlimited_test",
        scope="read",
        rate_limit_rpm=None,
        rate_limit_rph=None,
        rate_limit_rpd=None,
        is_active=True
    )
    db_session.add(api_key)
    await db_session.commit()

    response = await client.get(
        "/auth/check",
        headers={"X-API-Key": raw_key}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["rate_limits"]["rpm"] is None
    assert data["rate_limits"]["rph"] is None
    assert data["rate_limits"]["rpd"] is None
    assert data["remaining"]["rpm_remaining"] is None
    assert data["remaining"]["rph_remaining"] is None
    assert data["remaining"]["rpd_remaining"] is None
