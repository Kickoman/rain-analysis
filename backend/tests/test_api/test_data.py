"""Tests for the /api/v1/data endpoints (ingest, series, current values)."""

import pytest
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import APIKey, Measurement, Sensor
from app.auth.crypto import generate_api_key


def _make_key(scope: str) -> tuple[str, APIKey]:
    full_key, key_hash, key_prefix = generate_api_key("test")
    return full_key, APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner=f"test_{scope}",
        description=f"Test {scope} key",
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


@pytest.fixture
async def admin_key(db_session: AsyncSession) -> str:
    full_key, key = _make_key("admin")
    db_session.add(key)
    await db_session.commit()
    return full_key


BASE_TS = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)


def ingest_payload(rows):
    return {"source": "ha", "measurements": rows}


@pytest.mark.asyncio
async def test_ingest_creates_and_autoregisters(client: AsyncClient, write_key, db_session):
    payload = ingest_payload([
        {"sensor": "sensor.rain_probability", "timestamp": BASE_TS.isoformat(), "value": "42.5"},
        {"sensor": "sensor.rain_probability", "timestamp": (BASE_TS + timedelta(minutes=5)).isoformat(), "value": "43"},
    ])
    response = await client.post(
        "/api/v1/data/measurements", json=payload, headers={"X-API-Key": write_key}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] == 2
    assert data["created"] == 2
    assert data["updated"] == 0
    assert data["skipped_invalid"] == []

    sensor = (
        await db_session.execute(select(Sensor).where(Sensor.name == "sensor.rain_probability"))
    ).scalar_one()
    assert sensor.sensor_type == "numeric"
    rows = (
        await db_session.execute(select(Measurement).where(Measurement.sensor_id == sensor.id))
    ).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_ingest_is_idempotent(client: AsyncClient, write_key, db_session):
    payload = ingest_payload(
        [{"sensor": "sensor.rain_probability", "timestamp": BASE_TS.isoformat(), "value": "42.5"}]
    )
    headers = {"X-API-Key": write_key}
    first = await client.post("/api/v1/data/measurements", json=payload, headers=headers)
    assert first.json()["created"] == 1

    payload["measurements"][0]["value"] = "50"
    second = await client.post("/api/v1/data/measurements", json=payload, headers=headers)
    data = second.json()
    assert data["created"] == 0
    assert data["updated"] == 1

    rows = (await db_session.execute(select(Measurement))).scalars().all()
    assert len(rows) == 1
    assert rows[0].value == "50"


@pytest.mark.asyncio
async def test_ingest_skips_non_values_and_bad_names(client: AsyncClient, write_key):
    payload = ingest_payload([
        {"sensor": "sensor.ok", "timestamp": BASE_TS.isoformat(), "value": "1"},
        {"sensor": "sensor.ok", "timestamp": (BASE_TS + timedelta(minutes=1)).isoformat(), "value": "unavailable"},
        {"sensor": "sensor.ok", "timestamp": (BASE_TS + timedelta(minutes=2)).isoformat(), "value": "unknown"},
    ])
    response = await client.post(
        "/api/v1/data/measurements", json=payload, headers={"X-API-Key": write_key}
    )
    data = response.json()
    assert data["accepted"] == 1
    assert {s["index"] for s in data["skipped_invalid"]} == {1, 2}

    # Invalid sensor name fails request validation entirely (422)
    bad = ingest_payload([
        {"sensor": "Sensor With Spaces", "timestamp": BASE_TS.isoformat(), "value": "1"}
    ])
    response = await client.post(
        "/api/v1/data/measurements", json=bad, headers={"X-API-Key": write_key}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingest_requires_write_scope(client: AsyncClient, read_key):
    payload = ingest_payload(
        [{"sensor": "sensor.x", "timestamp": BASE_TS.isoformat(), "value": "1"}]
    )
    response = await client.post(
        "/api/v1/data/measurements", json=payload, headers={"X-API-Key": read_key}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_series_typed_decoding(client: AsyncClient, write_key, read_key, db_session):
    headers_w = {"X-API-Key": write_key}
    await client.post(
        "/api/v1/data/measurements",
        json=ingest_payload([
            {"sensor": "sensor.temp", "timestamp": BASE_TS.isoformat(), "value": "18.5"},
            {"sensor": "sensor.temp", "timestamp": (BASE_TS + timedelta(hours=1)).isoformat(), "value": "19.1"},
        ]),
        headers=headers_w,
    )
    # A row that will not decode as numeric (stored directly to bypass ingest checks)
    sensor = (
        await db_session.execute(select(Sensor).where(Sensor.name == "sensor.temp"))
    ).scalar_one()
    db_session.add(Measurement(
        sensor_id=sensor.id,
        timestamp=BASE_TS + timedelta(hours=2),
        value="garbled",
        source="test",
    ))
    await db_session.commit()

    response = await client.get(
        "/api/v1/data/measurements",
        params={"sensor": "sensor.temp"},
        headers={"X-API-Key": read_key},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    [series] = data["series"]
    assert series["type"] == "numeric"
    assert [p["v"] for p in series["points"]] == [18.5, 19.1, None]
    assert series["points"][2]["raw"] == "garbled"


@pytest.mark.asyncio
async def test_series_pagination_and_range(client: AsyncClient, write_key, read_key):
    rows = [
        {"sensor": "sensor.p", "timestamp": (BASE_TS + timedelta(hours=i)).isoformat(), "value": str(i)}
        for i in range(10)
    ]
    await client.post(
        "/api/v1/data/measurements", json=ingest_payload(rows), headers={"X-API-Key": write_key}
    )

    response = await client.get(
        "/api/v1/data/measurements",
        params={"sensor": "sensor.p", "page": 2, "page_size": 4},
        headers={"X-API-Key": read_key},
    )
    data = response.json()
    assert data["total"] == 10
    [series] = data["series"]
    assert [p["v"] for p in series["points"]] == [4.0, 5.0, 6.0, 7.0]

    response = await client.get(
        "/api/v1/data/measurements",
        params={
            "sensor": "sensor.p",
            "start": (BASE_TS + timedelta(hours=8)).isoformat(),
        },
        headers={"X-API-Key": read_key},
    )
    assert response.json()["total"] == 2


@pytest.mark.asyncio
async def test_current_values(client: AsyncClient, write_key, read_key):
    await client.post(
        "/api/v1/data/measurements",
        json=ingest_payload([
            {"sensor": "sensor.rain_probability", "timestamp": BASE_TS.isoformat(), "value": "40"},
            {"sensor": "sensor.rain_probability", "timestamp": (BASE_TS + timedelta(hours=1)).isoformat(), "value": "52"},
        ]),
        headers={"X-API-Key": write_key},
    )

    response = await client.get(
        "/api/v1/data/current",
        params={"sensors": "sensor.rain_probability,sensor.missing"},
        headers={"X-API-Key": read_key},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "max-age=15"
    values = {v["sensor"]: v for v in response.json()["values"]}
    assert values["sensor.rain_probability"]["value"] == 52.0
    assert values["sensor.rain_probability"]["age_seconds"] >= 0
    assert values["sensor.missing"]["value"] is None


@pytest.mark.asyncio
async def test_sensors_list_and_admin_patch(client: AsyncClient, write_key, admin_key, read_key):
    await client.post(
        "/api/v1/data/measurements",
        json=ingest_payload(
            [{"sensor": "sensor.rain_probability", "timestamp": BASE_TS.isoformat(), "value": "40"}]
        ),
        headers={"X-API-Key": write_key},
    )

    response = await client.get(
        "/api/v1/data/sensors",
        params={"include_stats": "true"},
        headers={"X-API-Key": read_key},
    )
    assert response.status_code == 200
    [sensor] = response.json()
    assert sensor["name"] == "sensor.rain_probability"
    assert sensor["measurement_count"] == 1
    assert sensor["latest_timestamp"] is not None

    # Read key cannot patch
    response = await client.patch(
        f"/api/v1/data/sensors/{sensor['id']}",
        json={"unit": "%"},
        headers={"X-API-Key": read_key},
    )
    assert response.status_code == 403

    response = await client.patch(
        f"/api/v1/data/sensors/{sensor['id']}",
        json={"unit": "%", "description": "HA template model output"},
        headers={"X-API-Key": admin_key},
    )
    assert response.status_code == 200
    assert response.json()["unit"] == "%"
