"""Sensor data endpoints: ingest, series, current values (issues #221/#412)."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_admin, require_api_key
from ..database import get_db
from ..models import APIKey, Measurement, Sensor
from ..schemas.measurement import (
    CurrentValuesResponse,
    IngestRequest,
    IngestResponse,
    MeasurementSeriesResponse,
)
from ..schemas.sensor import SensorUpdate, SensorWithStats
from ..services import measurement_service

router = APIRouter(prefix="/data", tags=["data"])


@router.post("/measurements", response_model=IngestResponse)
async def ingest(
    payload: IngestRequest,
    api_key: APIKey = Depends(require_api_key("write")),
    db: AsyncSession = Depends(get_db),
):
    """
    Batch-ingest measurements (idempotent).

    Rows are upserted on (sensor, timestamp); re-sending the same batch is
    safe. Invalid rows are reported in `skipped_invalid` without failing
    the batch. Unknown sensors are auto-registered as numeric.
    """
    return await measurement_service.ingest_measurements(db, payload)


@router.get("/sensors", response_model=list[SensorWithStats])
async def list_sensors(
    include_stats: bool = Query(False, description="Include latest timestamp and row count per sensor"),
    api_key: APIKey = Depends(require_api_key("read")),
    db: AsyncSession = Depends(get_db),
):
    """List registered sensors."""
    result = await db.execute(select(Sensor).order_by(Sensor.name))
    sensors = list(result.scalars())
    responses = [SensorWithStats.model_validate(s) for s in sensors]

    if include_stats and sensors:
        stats = await db.execute(
            select(
                Measurement.sensor_id,
                func.max(Measurement.timestamp),
                func.count(Measurement.id),
            ).group_by(Measurement.sensor_id)
        )
        by_id = {sid: (latest, count) for sid, latest, count in stats.all()}
        for sensor, response in zip(sensors, responses):
            latest, count = by_id.get(sensor.id, (None, 0))
            response.latest_timestamp = latest
            response.measurement_count = count

    return responses


@router.patch("/sensors/{sensor_id}", response_model=SensorWithStats)
async def update_sensor(
    sensor_id: int,
    update: SensorUpdate,
    api_key: APIKey = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Fix metadata (unit, type, description) of a sensor, e.g. after auto-registration."""
    sensor = (
        await db.execute(select(Sensor).where(Sensor.id == sensor_id))
    ).scalar_one_or_none()
    if sensor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sensor not found")

    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(sensor, field, value)
    await db.commit()
    await db.refresh(sensor)
    return SensorWithStats.model_validate(sensor)


@router.get("/measurements", response_model=MeasurementSeriesResponse)
async def get_measurements(
    sensor: list[str] = Query(..., min_length=1, max_length=5, description="Sensor name(s)"),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(500, ge=1, le=5000),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    api_key: APIKey = Depends(require_api_key("read")),
    db: AsyncSession = Depends(get_db),
):
    """
    Typed measurement series.

    Values are decoded server-side per the sensor's type; rows that fail to
    decode come back with `v: null` and the raw stored text in `raw`.
    """
    series, total = await measurement_service.get_series(
        db, sensor, start, end, page, page_size, ascending=(order == "asc")
    )
    return MeasurementSeriesResponse(series=series, page=page, page_size=page_size, total=total)


@router.get("/current", response_model=CurrentValuesResponse)
async def get_current(
    response: Response,
    sensors: str = Query(..., description="Comma-separated sensor names"),
    api_key: APIKey = Depends(require_api_key("read")),
    db: AsyncSession = Depends(get_db),
):
    """
    Latest value per sensor — the cheap polling endpoint for widgets.

    Unknown sensors are returned with `value: null` rather than 404 so a
    client polling several sensors never breaks on one missing entity.
    """
    names = [n.strip() for n in sensors.split(",") if n.strip()]
    if not names or len(names) > 20:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide between 1 and 20 sensor names",
        )
    values = await measurement_service.get_current_values(db, names)
    response.headers["Cache-Control"] = "max-age=15"
    return CurrentValuesResponse(values=values)
