"""
End-to-end authentication tests.

Tests the complete authentication flow:
1. Create admin key
2. Use admin key to create read key
3. Use read key to access data
4. Test rate limiting
5. Deactivate key
6. Verify key no longer works
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from datetime import datetime, timedelta

from app.models.api_key import APIKey
from app.models.api_request_log import APIRequestLog
from app.auth.crypto import generate_api_key, hash_api_key


@pytest.mark.asyncio
async def test_full_authentication_flow(client: AsyncClient, db_session):
    """Test complete authentication flow from admin key creation to key revocation."""
    
    # Step 1: Create admin key directly in database (simulating create_admin_key.py)
    admin_key_value, admin_key_hash, _ = generate_api_key()
    admin_key = APIKey(
        name="test-admin",
        key_hash=admin_key_hash,
        scopes=["admin"],
        rate_limit_rpm=1000,
        rate_limit_rph=10000,
        rate_limit_rpd=100000,
        is_active=True,
        created_at=datetime.utcnow()
    )
    db_session.add(admin_key)
    await db_session.commit()
    await db_session.refresh(admin_key)
    
    print(f"\n✓ Step 1: Admin key created (ID: {admin_key.id})")
    
    # Step 2: Use admin key to create a read-only key
    response = await client.post(
        "/admin/keys",
        headers={"X-API-Key": admin_key_value},
        json={
            "name": "test-read-key",
            "scopes": ["read"],
            "rate_limit_rpm": 10,
            "rate_limit_rph": 100,
            "rate_limit_rpd": 1000
        }
    )
    assert response.status_code == 201
    read_key_data = response.json()
    read_key_value = read_key_data["key"]
    read_key_id = read_key_data["id"]
    
    print(f"✓ Step 2: Read key created via API (ID: {read_key_id})")
    
    # Step 3: Use read key to access data (health endpoint)
    response = await client.get(
        "/health",
        headers={"X-API-Key": read_key_value}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    
    print(f"✓ Step 3: Read key successfully accessed /health endpoint")
    
    # Step 4: Check authentication status
    response = await client.get(
        "/auth/check",
        headers={"X-API-Key": read_key_value}
    )
    assert response.status_code == 200
    auth_status = response.json()
    assert auth_status["valid"] is True
    assert auth_status["key_name"] == "test-read-key"
    assert "read" in auth_status["scopes"]
    assert "rate_limits" in auth_status
    assert "rpm" in auth_status["rate_limits"]
    
    print(f"✓ Step 4: Auth check successful, rate limits: "
          f"RPM {auth_status['rate_limits']['rpm']['remaining']}/{auth_status['rate_limits']['rpm']['limit']}")
    
    # Step 5: Test rate limiting by making multiple requests
    rate_limit_rpm = 10
    successful_requests = 0
    
    for i in range(rate_limit_rpm + 2):
        response = await client.get(
            "/health",
            headers={"X-API-Key": read_key_value}
        )
        if response.status_code == 200:
            successful_requests += 1
        elif response.status_code == 429:
            # Rate limit exceeded
            error = response.json()
            assert "rate_limit_exceeded" in error["error"]
            break
    
    assert successful_requests <= rate_limit_rpm, "Rate limiting did not trigger"
    print(f"✓ Step 5: Rate limiting working ({successful_requests} requests succeeded before limit)")
    
    # Step 6: Admin deactivates the read key
    response = await client.delete(
        f"/admin/keys/{read_key_id}",
        headers={"X-API-Key": admin_key_value}
    )
    assert response.status_code == 200
    
    print(f"✓ Step 6: Read key deactivated by admin")
    
    # Step 7: Verify deactivated key no longer works
    response = await client.get(
        "/health",
        headers={"X-API-Key": read_key_value}
    )
    assert response.status_code == 401
    error = response.json()
    assert "unauthorized" in error["error"]
    
    print(f"✓ Step 7: Deactivated key rejected (401 Unauthorized)")
    
    # Step 8: Verify admin key still works
    response = await client.get(
        "/health",
        headers={"X-API-Key": admin_key_value}
    )
    assert response.status_code == 200
    
    print(f"✓ Step 8: Admin key still functional")
    
    print("\n✅ Full authentication flow test passed!")


@pytest.mark.asyncio
async def test_scope_enforcement(client: AsyncClient, db_session):
    """Test that scopes are properly enforced."""
    
    # Create read-only key
    read_key_value, read_key_hash, _ = generate_api_key()
    read_key = APIKey(
        name="read-only-test",
        key_hash=read_key_hash,
        scopes=["read"],
        rate_limit_rpm=100,
        rate_limit_rph=1000,
        rate_limit_rpd=10000,
        is_active=True,
        created_at=datetime.utcnow()
    )
    db_session.add(read_key)
    await db_session.commit()
    
    # Try to use read key on admin endpoint (should fail)
    response = await client.get(
        "/admin/keys",
        headers={"X-API-Key": read_key_value}
    )
    assert response.status_code == 403
    error = response.json()
    assert "forbidden" in error["error"]
    assert "admin" in error["detail"].lower()
    
    print("✓ Scope enforcement: read key correctly denied admin access")


@pytest.mark.asyncio
async def test_key_expiration(client: AsyncClient, db_session):
    """Test that expired keys are rejected."""
    
    # Create expired key
    expired_key_value, expired_key_hash, _ = generate_api_key()
    expired_key = APIKey(
        name="expired-test",
        key_hash=expired_key_hash,
        scopes=["read"],
        rate_limit_rpm=100,
        rate_limit_rph=1000,
        rate_limit_rpd=10000,
        is_active=True,
        expires_at=datetime.utcnow() - timedelta(days=1),  # Expired yesterday
        created_at=datetime.utcnow() - timedelta(days=30)
    )
    db_session.add(expired_key)
    await db_session.commit()
    
    # Try to use expired key
    response = await client.get(
        "/health",
        headers={"X-API-Key": expired_key_value}
    )
    assert response.status_code == 401
    error = response.json()
    assert "unauthorized" in error["error"]
    
    print("✓ Key expiration: expired key correctly rejected")


@pytest.mark.asyncio
async def test_rate_limit_reset(client: AsyncClient, db_session):
    """Test that rate limits reset properly."""
    
    # Create key with very low RPM limit
    test_key_value, test_key_hash, _ = generate_api_key()
    test_key = APIKey(
        name="rate-limit-test",
        key_hash=test_key_hash,
        scopes=["read"],
        rate_limit_rpm=2,  # Very low limit for testing
        rate_limit_rph=1000,
        rate_limit_rpd=10000,
        is_active=True,
        created_at=datetime.utcnow()
    )
    db_session.add(test_key)
    await db_session.commit()
    
    # Make requests until rate limited
    for i in range(5):
        response = await client.get(
            "/health",
            headers={"X-API-Key": test_key_value}
        )
        if response.status_code == 429:
            break
    
    assert response.status_code == 429, "Rate limit should have been triggered"
    
    # Check auth to get reset time
    response = await client.get(
        "/auth/check",
        headers={"X-API-Key": test_key_value}
    )
    
    # Even rate-limited keys should be able to check auth status
    if response.status_code == 200:
        auth_data = response.json()
        assert auth_data["rate_limits"]["rpm"]["remaining"] == 0
        assert "reset_at" in auth_data["rate_limits"]["rpm"]
        print(f"✓ Rate limit reset: RPM will reset at {auth_data['rate_limits']['rpm']['reset_at']}")


@pytest.mark.asyncio
async def test_multiple_scopes(client: AsyncClient, db_session):
    """Test key with multiple scopes."""
    
    # Create admin key
    admin_key_value, admin_key_hash, _ = generate_api_key()
    admin_key = APIKey(
        name="multi-scope-admin",
        key_hash=admin_key_hash,
        scopes=["admin"],
        rate_limit_rpm=100,
        rate_limit_rph=1000,
        rate_limit_rpd=10000,
        is_active=True,
        created_at=datetime.utcnow()
    )
    db_session.add(admin_key)
    await db_session.commit()
    
    # Create key with both read and write scopes
    response = await client.post(
        "/admin/keys",
        headers={"X-API-Key": admin_key_value},
        json={
            "name": "read-write-key",
            "scopes": ["read", "write"],
            "rate_limit_rpm": 60
        }
    )
    assert response.status_code == 201
    multi_scope_key = response.json()["key"]
    
    # Verify both scopes are present
    response = await client.get(
        "/auth/check",
        headers={"X-API-Key": multi_scope_key}
    )
    assert response.status_code == 200
    auth_data = response.json()
    assert set(auth_data["scopes"]) == {"read", "write"}
    
    print("✓ Multiple scopes: read+write key created and verified")


@pytest.mark.asyncio
async def test_audit_logging(client: AsyncClient, db_session):
    """Test that admin actions are logged."""
    
    # Create admin key
    admin_key_value, admin_key_hash, _ = generate_api_key()
    admin_key = APIKey(
        name="audit-test-admin",
        key_hash=admin_key_hash,
        scopes=["admin"],
        rate_limit_rpm=100,
        rate_limit_rph=1000,
        rate_limit_rpd=10000,
        is_active=True,
        created_at=datetime.utcnow()
    )
    db_session.add(admin_key)
    await db_session.commit()
    await db_session.refresh(admin_key)
    
    # Perform admin action (create key)
    response = await client.post(
        "/admin/keys",
        headers={"X-API-Key": admin_key_value},
        json={
            "name": "audit-test-key",
            "scopes": ["read"],
            "rate_limit_rpm": 60
        }
    )
    assert response.status_code == 201
    new_key_id = response.json()["id"]
    
    # Check audit log
    from app.models.admin_audit_log import AdminAuditLog
    result = await db_session.execute(
        select(AdminAuditLog)
        .where(AdminAuditLog.api_key_id == admin_key.id)
        .where(AdminAuditLog.action == "create_key")
    )
    audit_entry = result.scalar_one_or_none()
    
    assert audit_entry is not None, "Audit log entry should exist"
    assert audit_entry.target_key_id == new_key_id
    assert "audit-test-key" in str(audit_entry.details)
    
    print(f"✓ Audit logging: create_key action logged (entry ID: {audit_entry.id})")


@pytest.mark.asyncio
async def test_concurrent_requests_rate_limiting(client: AsyncClient, db_session):
    """Test rate limiting with concurrent requests."""
    import asyncio
    
    # Create key with low RPM limit
    test_key_value, test_key_hash, _ = generate_api_key()
    test_key = APIKey(
        name="concurrent-test",
        key_hash=test_key_hash,
        scopes=["read"],
        rate_limit_rpm=5,
        rate_limit_rph=1000,
        rate_limit_rpd=10000,
        is_active=True,
        created_at=datetime.utcnow()
    )
    db_session.add(test_key)
    await db_session.commit()
    
    # Make concurrent requests
    async def make_request():
        return await client.get(
            "/health",
            headers={"X-API-Key": test_key_value}
        )
    
    tasks = [make_request() for _ in range(10)]
    responses = await asyncio.gather(*tasks)
    
    success_count = sum(1 for r in responses if r.status_code == 200)
    rate_limited_count = sum(1 for r in responses if r.status_code == 429)
    
    assert success_count <= 5, "Should not exceed RPM limit"
    assert rate_limited_count > 0, "Some requests should be rate limited"
    
    print(f"✓ Concurrent rate limiting: {success_count} succeeded, {rate_limited_count} rate-limited")
