"""Integration tests for admin endpoints."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta

from backend.app.models import APIKey, AdminAuditLog
from backend.app.auth.crypto import generate_api_key


@pytest.fixture
async def admin_key(db_session: AsyncSession) -> tuple[str, APIKey]:
    """Create an admin API key for testing."""
    full_key, key_hash, key_prefix = generate_api_key("test")
    
    admin = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="test_admin",
        description="Test admin key",
        scope="admin",
        is_active=True
    )
    
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    
    return full_key, admin


@pytest.fixture
async def read_key(db_session: AsyncSession) -> tuple[str, APIKey]:
    """Create a read-only API key for testing authorization."""
    full_key, key_hash, key_prefix = generate_api_key("test")
    
    read_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="test_reader",
        description="Test read key",
        scope="read",
        is_active=True
    )
    
    db_session.add(read_key)
    await db_session.commit()
    await db_session.refresh(read_key)
    
    return full_key, read_key


@pytest.mark.asyncio
async def test_create_api_key_success(client: AsyncClient, admin_key: tuple[str, APIKey], db_session: AsyncSession):
    """Test successful API key creation by admin."""
    admin_token, admin_obj = admin_key
    
    key_data = {
        "owner": "test_user",
        "description": "Test API key",
        "scope": "read",
        "rate_limit_rpm": 60,
        "rate_limit_rph": 1000,
        "environment": "test"
    }
    
    response = await client.post(
        "/admin/keys",
        json=key_data,
        headers={"X-API-Key": admin_token}
    )
    
    assert response.status_code == 201
    data = response.json()
    
    # Check that full key is returned
    assert "key" in data
    assert data["key"].startswith("ra_test_")
    
    # Check key_info
    assert "key_info" in data
    key_info = data["key_info"]
    assert key_info["owner"] == "test_user"
    assert key_info["description"] == "Test API key"
    assert key_info["scope"] == "read"
    assert key_info["rate_limit_rpm"] == 60
    assert key_info["rate_limit_rph"] == 1000
    assert key_info["is_active"] is True
    
    # Verify key was created in database
    result = await db_session.execute(
        select(APIKey).where(APIKey.id == key_info["id"])
    )
    created_key = result.scalar_one()
    assert created_key.owner == "test_user"
    
    # Verify audit log was created
    audit_result = await db_session.execute(
        select(AdminAuditLog).where(
            AdminAuditLog.admin_key_id == admin_obj.id,
            AdminAuditLog.action == "create_key",
            AdminAuditLog.target_key_id == created_key.id
        )
    )
    audit_log = audit_result.scalar_one()
    assert audit_log.details["owner"] == "test_user"
    assert audit_log.details["scope"] == "read"


@pytest.mark.asyncio
async def test_create_api_key_non_admin_forbidden(client: AsyncClient, read_key: tuple[str, APIKey]):
    """Test that non-admin users cannot create API keys."""
    read_token, _ = read_key
    
    key_data = {
        "owner": "test_user",
        "scope": "read",
        "environment": "test"
    }
    
    response = await client.post(
        "/admin/keys",
        json=key_data,
        headers={"X-API-Key": read_token}
    )
    
    assert response.status_code == 403
    assert "Admin access required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_api_key_no_auth(client: AsyncClient):
    """Test that unauthenticated requests are rejected."""
    key_data = {
        "owner": "test_user",
        "scope": "read",
        "environment": "test"
    }
    
    response = await client.post("/admin/keys", json=key_data)
    
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_api_keys(client: AsyncClient, admin_key: tuple[str, APIKey], db_session: AsyncSession):
    """Test listing all API keys."""
    admin_token, _ = admin_key
    
    # Create additional test keys
    for i in range(3):
        full_key, key_hash, key_prefix = generate_api_key("test")
        test_key = APIKey(
            key_hash=key_hash,
            key_prefix=key_prefix,
            owner=f"user_{i}",
            scope="read",
            is_active=True
        )
        db_session.add(test_key)
    
    await db_session.commit()
    
    response = await client.get(
        "/admin/keys",
        headers={"X-API-Key": admin_token}
    )
    
    assert response.status_code == 200
    keys = response.json()
    
    # Should have at least 4 keys (1 admin + 3 created)
    assert len(keys) >= 4
    
    # Check structure
    for key in keys:
        assert "id" in key
        assert "key_prefix" in key
        assert "owner" in key
        assert "scope" in key
        assert "is_active" in key
        assert "key" not in key  # Full key should not be in list response


@pytest.mark.asyncio
async def test_get_api_key(client: AsyncClient, admin_key: tuple[str, APIKey], db_session: AsyncSession):
    """Test getting a specific API key."""
    admin_token, admin_obj = admin_key
    
    response = await client.get(
        f"/admin/keys/{admin_obj.id}",
        headers={"X-API-Key": admin_token}
    )
    
    assert response.status_code == 200
    key = response.json()
    
    assert key["id"] == admin_obj.id
    assert key["owner"] == "test_admin"
    assert key["scope"] == "admin"
    assert "key" not in key  # Full key should not be in response


@pytest.mark.asyncio
async def test_get_api_key_not_found(client: AsyncClient, admin_key: tuple[str, APIKey]):
    """Test getting a non-existent API key."""
    admin_token, _ = admin_key
    
    response = await client.get(
        "/admin/keys/99999",
        headers={"X-API-Key": admin_token}
    )
    
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_api_key_rate_limits(client: AsyncClient, admin_key: tuple[str, APIKey], db_session: AsyncSession):
    """Test updating API key rate limits."""
    admin_token, admin_obj = admin_key
    
    # Create a test key to update
    full_key, key_hash, key_prefix = generate_api_key("test")
    test_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="test_user",
        scope="read",
        rate_limit_rpm=60,
        is_active=True
    )
    db_session.add(test_key)
    await db_session.commit()
    await db_session.refresh(test_key)
    
    update_data = {
        "rate_limit_rpm": 120,
        "rate_limit_rph": 5000
    }
    
    response = await client.patch(
        f"/admin/keys/{test_key.id}",
        json=update_data,
        headers={"X-API-Key": admin_token}
    )
    
    assert response.status_code == 200
    updated_key = response.json()
    
    assert updated_key["rate_limit_rpm"] == 120
    assert updated_key["rate_limit_rph"] == 5000
    
    # Verify in database
    await db_session.refresh(test_key)
    assert test_key.rate_limit_rpm == 120
    assert test_key.rate_limit_rph == 5000
    
    # Verify audit log
    audit_result = await db_session.execute(
        select(AdminAuditLog).where(
            AdminAuditLog.admin_key_id == admin_obj.id,
            AdminAuditLog.action == "update_key",
            AdminAuditLog.target_key_id == test_key.id
        )
    )
    audit_log = audit_result.scalar_one()
    assert audit_log.details["rate_limit_rpm"] == 120
    assert audit_log.details["rate_limit_rph"] == 5000


@pytest.mark.asyncio
async def test_update_api_key_deactivate(client: AsyncClient, admin_key: tuple[str, APIKey], db_session: AsyncSession):
    """Test deactivating an API key via update."""
    admin_token, _ = admin_key
    
    # Create a test key to deactivate
    full_key, key_hash, key_prefix = generate_api_key("test")
    test_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="test_user",
        scope="read",
        is_active=True
    )
    db_session.add(test_key)
    await db_session.commit()
    await db_session.refresh(test_key)
    
    update_data = {"is_active": False}
    
    response = await client.patch(
        f"/admin/keys/{test_key.id}",
        json=update_data,
        headers={"X-API-Key": admin_token}
    )
    
    assert response.status_code == 200
    updated_key = response.json()
    assert updated_key["is_active"] is False
    
    # Verify in database
    await db_session.refresh(test_key)
    assert test_key.is_active is False


@pytest.mark.asyncio
async def test_deactivate_api_key(client: AsyncClient, admin_key: tuple[str, APIKey], db_session: AsyncSession):
    """Test deactivating an API key via DELETE."""
    admin_token, admin_obj = admin_key
    
    # Create a test key to deactivate
    full_key, key_hash, key_prefix = generate_api_key("test")
    test_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="test_user",
        scope="read",
        is_active=True
    )
    db_session.add(test_key)
    await db_session.commit()
    await db_session.refresh(test_key)
    
    response = await client.delete(
        f"/admin/keys/{test_key.id}",
        headers={"X-API-Key": admin_token}
    )
    
    assert response.status_code == 204
    
    # Verify key is deactivated in database
    await db_session.refresh(test_key)
    assert test_key.is_active is False
    
    # Verify audit log
    audit_result = await db_session.execute(
        select(AdminAuditLog).where(
            AdminAuditLog.admin_key_id == admin_obj.id,
            AdminAuditLog.action == "deactivate_key",
            AdminAuditLog.target_key_id == test_key.id
        )
    )
    audit_log = audit_result.scalar_one()
    assert audit_log.details["key_prefix"] == test_key.key_prefix


@pytest.mark.asyncio
async def test_deactivate_already_inactive_key(client: AsyncClient, admin_key: tuple[str, APIKey], db_session: AsyncSession):
    """Test that deactivating an already inactive key returns an error."""
    admin_token, _ = admin_key
    
    # Create an already inactive key
    full_key, key_hash, key_prefix = generate_api_key("test")
    test_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="test_user",
        scope="read",
        is_active=False
    )
    db_session.add(test_key)
    await db_session.commit()
    await db_session.refresh(test_key)
    
    response = await client.delete(
        f"/admin/keys/{test_key.id}",
        headers={"X-API-Key": admin_token}
    )
    
    assert response.status_code == 400
    assert "already inactive" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_api_key_with_expiry(client: AsyncClient, admin_key: tuple[str, APIKey], db_session: AsyncSession):
    """Test creating an API key with expiration date."""
    admin_token, _ = admin_key
    
    expiry = (datetime.utcnow() + timedelta(days=30)).isoformat()
    
    key_data = {
        "owner": "test_user",
        "scope": "read",
        "environment": "test",
        "expires_at": expiry
    }
    
    response = await client.post(
        "/admin/keys",
        json=key_data,
        headers={"X-API-Key": admin_token}
    )
    
    assert response.status_code == 201
    data = response.json()
    
    # Check expiration was set
    assert data["key_info"]["expires_at"] is not None


@pytest.mark.asyncio
async def test_create_api_key_validation_errors(client: AsyncClient, admin_key: tuple[str, APIKey]):
    """Test validation errors when creating API keys."""
    admin_token, _ = admin_key
    
    # Invalid scope
    response = await client.post(
        "/admin/keys",
        json={
            "owner": "test",
            "scope": "invalid_scope",
            "environment": "test"
        },
        headers={"X-API-Key": admin_token}
    )
    assert response.status_code == 422
    
    # Invalid environment
    response = await client.post(
        "/admin/keys",
        json={
            "owner": "test",
            "scope": "read",
            "environment": "production"
        },
        headers={"X-API-Key": admin_token}
    )
    assert response.status_code == 422
    
    # Invalid rate limit (negative)
    response = await client.post(
        "/admin/keys",
        json={
            "owner": "test",
            "scope": "read",
            "environment": "test",
            "rate_limit_rpm": -10
        },
        headers={"X-API-Key": admin_token}
    )
    assert response.status_code == 422
