"""Tests for the /api/v1/reports endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import APIKey, Report
from app.auth.crypto import generate_api_key


def _make_key(scope: str) -> tuple[str, APIKey]:
    full_key, key_hash, key_prefix = generate_api_key("test")
    return full_key, APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner=f"test_{scope}",
        scope=scope,
        is_active=True,
    )


@pytest.fixture
async def write_key(db_session: AsyncSession) -> str:
    full_key, key = _make_key("write")
    db_session.add(key)
    await db_session.commit()
    return full_key


@pytest.fixture
async def read_key(db_session: AsyncSession) -> str:
    full_key, key = _make_key("read")
    db_session.add(key)
    await db_session.commit()
    return full_key


def report_payload(report_date="2026-08-21", best_model="pressure_lagged"):
    return {
        "report_date": report_date,
        "content": {
            "executive_summary": {"best_model": best_model, "text": "Best day ever"},
            "models": [
                {"name": best_model, "metrics": {"f1": 0.557, "precision": 0.478, "recall": 0.667}},
                {"name": "ha_live_replica", "metrics": {"f1": 0.464, "precision": 0.4, "recall": None}},
            ],
        },
        "meta": {"source_markdown": "# Daily Model Analysis — 2026-08-21\n...", "generator": "test"},
    }


@pytest.mark.asyncio
async def test_upsert_creates_then_updates(client: AsyncClient, write_key, db_session):
    headers = {"X-API-Key": write_key}
    first = await client.post("/api/v1/reports", json=report_payload(), headers=headers)
    assert first.status_code == 200
    assert first.json()["action"] == "created"

    second = await client.post(
        "/api/v1/reports", json=report_payload(best_model="combined"), headers=headers
    )
    assert second.json()["action"] == "updated"

    rows = (await db_session.execute(select(Report))).scalars().all()
    assert len(rows) == 1
    assert rows[0].content["executive_summary"]["best_model"] == "combined"
    assert rows[0].updated_at is not None


@pytest.mark.asyncio
async def test_upsert_requires_write_scope(client: AsyncClient, read_key):
    response = await client.post(
        "/api/v1/reports", json=report_payload(), headers={"X-API-Key": read_key}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_report_hides_markdown_by_default(client: AsyncClient, write_key, read_key):
    await client.post("/api/v1/reports", json=report_payload(), headers={"X-API-Key": write_key})

    response = await client.get("/api/v1/reports/2026-08-21", headers={"X-API-Key": read_key})
    assert response.status_code == 200
    data = response.json()
    assert data["report_date"] == "2026-08-21"
    assert "source_markdown" not in (data["meta"] or {})
    assert data["meta"]["generator"] == "test"

    response = await client.get(
        "/api/v1/reports/2026-08-21",
        params={"include_markdown": "true"},
        headers={"X-API-Key": read_key},
    )
    assert "source_markdown" in response.json()["meta"]


@pytest.mark.asyncio
async def test_get_report_404(client: AsyncClient, read_key):
    response = await client.get("/api/v1/reports/1999-01-01", headers={"X-API-Key": read_key})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_and_latest(client: AsyncClient, write_key, read_key):
    headers = {"X-API-Key": write_key}
    for day, model in [("2026-08-19", "combined"), ("2026-08-20", "tuned"), ("2026-08-21", "onset_gate")]:
        await client.post("/api/v1/reports", json=report_payload(day, model), headers=headers)

    response = await client.get("/api/v1/reports", headers={"X-API-Key": read_key})
    data = response.json()
    assert data["total"] == 3
    assert [r["report_date"] for r in data["reports"]] == ["2026-08-21", "2026-08-20", "2026-08-19"]
    assert data["reports"][0]["best_model"] == "onset_gate"

    response = await client.get(
        "/api/v1/reports",
        params={"start": "2026-08-20", "end": "2026-08-20"},
        headers={"X-API-Key": read_key},
    )
    assert response.json()["total"] == 1

    response = await client.get("/api/v1/reports/latest", headers={"X-API-Key": read_key})
    assert response.json()["report_date"] == "2026-08-21"


@pytest.mark.asyncio
async def test_latest_404_when_empty(client: AsyncClient, read_key):
    response = await client.get("/api/v1/reports/latest", headers={"X-API-Key": read_key})
    assert response.status_code == 404
