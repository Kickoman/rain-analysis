"""
End-to-end authentication tests.

The complete flow against the real API surface:
admin key -> create keys via API -> scope enforcement -> rate limiting ->
expiry -> revocation -> audit trail.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from datetime import datetime, timedelta

from app.models import AdminAuditLog, APIKey
from app.auth.crypto import generate_api_key


async def seed_key(db_session, scope="admin", owner="e2e-admin", **kwargs) -> tuple[str, APIKey]:
    """Create a key directly in the DB (simulating create_admin_key.py)."""
    full_key, key_hash, key_prefix = generate_api_key("test")
    key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner=owner,
        scope=scope,
        is_active=True,
        **kwargs,
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)
    return full_key, key


@pytest.mark.asyncio
async def test_full_authentication_flow(client: AsyncClient, db_session):
    """Admin creates a read key via the API; the key works until revoked."""
    admin_value, admin_key = await seed_key(db_session)

    # Create a read-only key through the admin API
    response = await client.post(
        "/api/v1/admin/keys",
        headers={"X-API-Key": admin_value},
        json={
            "owner": "e2e-reader",
            "scope": "read",
            "environment": "test",
            "rate_limit_rpm": 10,
        },
    )
    assert response.status_code == 201
    created = response.json()
    read_value = created["key"]
    read_id = created["key_info"]["id"]

    # The new key authenticates
    response = await client.get("/api/v1/auth/check", headers={"X-API-Key": read_value})
    assert response.status_code == 200
    assert response.json()["scope"] == "read"

    # Revoke it via the admin API
    response = await client.delete(
        f"/api/v1/admin/keys/{read_id}", headers={"X-API-Key": admin_value}
    )
    assert response.status_code == 204

    # Revoked key no longer authenticates
    response = await client.get("/api/v1/auth/check", headers={"X-API-Key": read_value})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


@pytest.mark.asyncio
async def test_scope_enforcement(client: AsyncClient, db_session):
    """A read key must not reach admin endpoints."""
    read_value, _ = await seed_key(db_session, scope="read", owner="e2e-reader")

    response = await client.get("/api/v1/admin/keys", headers={"X-API-Key": read_value})
    assert response.status_code == 403
    assert "Insufficient permissions" in response.json()["detail"]

    # Missing key entirely
    response = await client.get("/api/v1/admin/keys")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing API key"


@pytest.mark.asyncio
async def test_key_expiration(client: AsyncClient, db_session):
    """Expired keys are rejected; unexpired ones are not."""
    expired_value, _ = await seed_key(
        db_session, scope="read", owner="expired",
        expires_at=datetime.utcnow() - timedelta(minutes=1),
    )
    response = await client.get("/api/v1/auth/check", headers={"X-API-Key": expired_value})
    assert response.status_code == 401
    assert response.json()["detail"] == "API key expired"

    valid_value, _ = await seed_key(
        db_session, scope="read", owner="not-expired",
        expires_at=datetime.utcnow() + timedelta(days=1),
    )
    response = await client.get("/api/v1/auth/check", headers={"X-API-Key": valid_value})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_enforced_and_isolated(client: AsyncClient, db_session):
    """The N+1th request within a minute is rejected; other keys unaffected."""
    limited_value, _ = await seed_key(
        db_session, scope="read", owner="limited", rate_limit_rpm=3
    )
    unlimited_value, _ = await seed_key(db_session, scope="read", owner="unlimited")

    for _ in range(3):
        response = await client.get("/api/v1/auth/check", headers={"X-API-Key": limited_value})
        assert response.status_code == 200

    response = await client.get("/api/v1/auth/check", headers={"X-API-Key": limited_value})
    assert response.status_code == 429
    assert response.json()["detail"] == "Rate limit exceeded"

    # A different key is not affected by the first key's counters
    response = await client.get("/api/v1/auth/check", headers={"X-API-Key": unlimited_value})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_scope_hierarchy(client: AsyncClient, db_session):
    """admin > write > read: higher scopes satisfy lower requirements."""
    admin_value, _ = await seed_key(db_session)

    # Admin passes a write-scoped endpoint (data ingest)
    response = await client.post(
        "/api/v1/data/measurements",
        headers={"X-API-Key": admin_value},
        json={"source": "test", "measurements": [
            {"sensor": "sensor.e2e", "timestamp": "2026-08-25T10:00:00Z", "value": "1"}
        ]},
    )
    assert response.status_code == 200

    # Write key passes ingest but not admin
    write_value, _ = await seed_key(db_session, scope="write", owner="writer")
    response = await client.get("/api/v1/admin/keys", headers={"X-API-Key": write_value})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_audit_logging(client: AsyncClient, db_session):
    """Admin actions land in the audit log."""
    admin_value, admin_key = await seed_key(db_session, owner="audit-admin")

    response = await client.post(
        "/api/v1/admin/keys",
        headers={"X-API-Key": admin_value},
        json={"owner": "audited", "scope": "read", "environment": "test"},
    )
    assert response.status_code == 201
    target_id = response.json()["key_info"]["id"]

    response = await client.delete(
        f"/api/v1/admin/keys/{target_id}", headers={"X-API-Key": admin_value}
    )
    assert response.status_code == 204

    logs = (
        await db_session.execute(
            select(AdminAuditLog).where(AdminAuditLog.admin_key_id == admin_key.id)
        )
    ).scalars().all()
    actions = {log.action for log in logs}
    assert "create_key" in actions
    assert any(log.target_key_id == target_id for log in logs)
