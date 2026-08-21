"""
End-to-end authentication tests.

Tests the complete authentication flow against the current API:
1. Create admin key directly in the database
2. Use admin key to create a read key via /admin/keys
3. Use read key to access a protected endpoint
4. Verify scope enforcement
5. Verify key expiration is rejected
6. Verify rate limiting
7. Verify audit logging
"""

import pytest
import asyncio
from httpx import AsyncClient
from sqlalchemy import select
from datetime import datetime, timedelta

from app.models.api_key import APIKey
from app.models.admin_audit_log import AdminAuditLog
from app.auth.crypto import generate_api_key


def _admin_key(db_session, owner="test-admin", **overrides):
    """Create an admin API key directly in the database."""
    full_key, key_hash, key_prefix = generate_api_key("test")
    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner=owner,
        description="Admin key",
        scope="admin",
        is_active=True,
        **overrides,
    )
    db_session.add(api_key)
    return full_key, api_key


@pytest.mark.asyncio
async def test_full_authentication_flow(client: AsyncClient, db_session):
    """Test complete authentication flow from admin key creation to key revocation."""

    # Step 1: Create admin key directly in the database
    admin_key_value, admin_key = _admin_key(db_session)
    await db_session.commit()
    await db_session.refresh(admin_key)

    # Step 2: Use admin key to create a read-only key
    response = await client.post(
        "/admin/keys",
        headers={"X-API-Key": admin_key_value},
        json={
            "owner": "test-read-key",
            "scope": "read",
            "rate_limit_rpm": 10,
            "environment": "test",
        },
    )
    assert response.status_code == 201
    read_key_data = response.json()
    read_key_value = read_key_data["key"]
    read_key_id = read_key_data["key_info"]["id"]

    # Step 3: Use read key to access a protected endpoint and check auth status
    response = await client.get(
        "/auth/check",
        headers={"X-API-Key": read_key_value},
    )
    assert response.status_code == 200
    auth_status = response.json()
    assert auth_status["valid"] is True
    assert auth_status["owner"] == "test-read-key"
    assert auth_status["scope"] == "read"
    assert "rate_limits" in auth_status
    assert "remaining" in auth_status

    # Step 4: Test rate limiting by making multiple requests
    rate_limit_rpm = 10
    successful_requests = 0
    rate_limited = False

    for _ in range(rate_limit_rpm + 2):
        response = await client.get(
            "/auth/check",
            headers={"X-API-Key": read_key_value},
        )
        if response.status_code == 200:
            successful_requests += 1
        elif response.status_code == 429:
            rate_limited = True
            assert response.json()["detail"] == "Rate limit exceeded"
            break

    assert successful_requests <= rate_limit_rpm, "Rate limiting did not trigger"
    assert rate_limited, "Expected at least one rate-limited request"

    # Step 5: Admin deactivates the read key
    response = await client.delete(
        f"/admin/keys/{read_key_id}",
        headers={"X-API-Key": admin_key_value},
    )
    assert response.status_code == 204

    # Step 6: Verify deactivated key no longer works
    response = await client.get(
        "/auth/check",
        headers={"X-API-Key": read_key_value},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"

    # Step 7: Verify admin key still works
    response = await client.get(
        "/auth/check",
        headers={"X-API-Key": admin_key_value},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_scope_enforcement(client: AsyncClient, db_session):
    """Test that scopes are properly enforced."""

    # Create read-only key
    read_key_value, read_key_hash, read_key_prefix = generate_api_key("test")
    read_key = APIKey(
        key_hash=read_key_hash,
        key_prefix=read_key_prefix,
        owner="read-only-test",
        scope="read",
        is_active=True,
    )
    db_session.add(read_key)
    await db_session.commit()

    # Try to use read key on admin endpoint (should fail)
    response = await client.get(
        "/admin/keys",
        headers={"X-API-Key": read_key_value},
    )
    assert response.status_code == 403
    assert "Admin access required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_key_expiration(client: AsyncClient, db_session):
    """Test that expired keys are rejected."""

    # Create expired key
    expired_key_value, expired_key_hash, expired_key_prefix = generate_api_key("test")
    expired_key = APIKey(
        key_hash=expired_key_hash,
        key_prefix=expired_key_prefix,
        owner="expired-test",
        scope="read",
        is_active=True,
        expires_at=datetime.utcnow() - timedelta(days=1),  # Expired yesterday
    )
    db_session.add(expired_key)
    await db_session.commit()

    # Try to use expired key on a protected endpoint
    response = await client.get(
        "/auth/check",
        headers={"X-API-Key": expired_key_value},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


@pytest.mark.asyncio
async def test_rate_limit_enforcement(client: AsyncClient, db_session):
    """Test that rate limits are enforced."""

    # Create key with a low RPM limit
    test_key_value, test_key_hash, test_key_prefix = generate_api_key("test")
    test_key = APIKey(
        key_hash=test_key_hash,
        key_prefix=test_key_prefix,
        owner="rate-limit-test",
        scope="read",
        rate_limit_rpm=2,  # Very low limit for testing
        is_active=True,
    )
    db_session.add(test_key)
    await db_session.commit()

    # Make requests until rate limited
    statuses = []
    for _ in range(5):
        response = await client.get(
            "/auth/check",
            headers={"X-API-Key": test_key_value},
        )
        statuses.append(response.status_code)

    assert 429 in statuses, "Rate limit should have been triggered"
    assert statuses.count(200) <= 2

    # A rate-limited key is rejected with 429 on further requests
    response = await client.get(
        "/auth/check",
        headers={"X-API-Key": test_key_value},
    )
    assert response.status_code == 429
    assert response.json()["detail"] == "Rate limit exceeded"


@pytest.mark.asyncio
async def test_write_scope(client: AsyncClient, db_session):
    """Test that a key with a specific scope is reported correctly."""

    # Create admin key
    admin_key_value, admin_key = _admin_key(db_session)
    await db_session.commit()

    # Create key with write scope
    response = await client.post(
        "/admin/keys",
        headers={"X-API-Key": admin_key_value},
        json={
            "owner": "write-key",
            "scope": "write",
            "rate_limit_rpm": 60,
            "environment": "test",
        },
    )
    assert response.status_code == 201
    write_key_value = response.json()["key"]

    # Verify scope is reported
    response = await client.get(
        "/auth/check",
        headers={"X-API-Key": write_key_value},
    )
    assert response.status_code == 200
    auth_data = response.json()
    assert auth_data["scope"] == "write"


@pytest.mark.asyncio
async def test_audit_logging(client: AsyncClient, db_session):
    """Test that admin actions are logged."""

    # Create admin key
    admin_key_value, admin_key = _admin_key(db_session)
    await db_session.commit()
    await db_session.refresh(admin_key)

    # Perform admin action (create key)
    response = await client.post(
        "/admin/keys",
        headers={"X-API-Key": admin_key_value},
        json={
            "owner": "audit-test-key",
            "scope": "read",
            "rate_limit_rpm": 60,
            "environment": "test",
        },
    )
    assert response.status_code == 201
    new_key_id = response.json()["key_info"]["id"]

    # Check audit log
    result = await db_session.execute(
        select(AdminAuditLog)
        .where(AdminAuditLog.admin_key_id == admin_key.id)
        .where(AdminAuditLog.action == "create_key")
    )
    audit_entry = result.scalar_one_or_none()

    assert audit_entry is not None, "Audit log entry should exist"
    assert audit_entry.target_key_id == new_key_id
    assert audit_entry.details["owner"] == "audit-test-key"


@pytest.mark.asyncio
async def test_rate_limiting_burst(client: AsyncClient, db_session):
    """Test that a burst of requests is capped exactly at the RPM limit.

    True concurrency on the rate limiter itself is covered by
    ``tests/test_rate_limiter.py::test_rate_limiter_thread_safety``. Here we
    verify the middleware enforces the limit for a burst of sequential requests.
    """

    # Create key with low RPM limit
    test_key_value, test_key_hash, test_key_prefix = generate_api_key("test")
    test_key = APIKey(
        key_hash=test_key_hash,
        key_prefix=test_key_prefix,
        owner="burst-test",
        scope="read",
        rate_limit_rpm=5,
        is_active=True,
    )
    db_session.add(test_key)
    await db_session.commit()

    responses = []
    for _ in range(10):
        response = await client.get(
            "/auth/check",
            headers={"X-API-Key": test_key_value},
        )
        responses.append(response.status_code)

    assert responses.count(200) == 5
    assert responses.count(429) == 5
