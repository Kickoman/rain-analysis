"""Measurement ingest and query logic shared by the data router.

Values live in the EAV ``measurements`` table as text (see #221/#417).
Everything that turns text back into typed values happens here, on the
server — clients always receive decoded series (#412).
"""

import re
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Measurement, Sensor
from ..schemas.measurement import (
    NON_VALUES,
    CurrentValue,
    IngestRequest,
    IngestResponse,
    IngestSkipped,
    SensorSeries,
    SeriesPoint,
)

SENSOR_NAME_RE = re.compile(r"^[a-z0-9_.]+$")

# Boolean spellings accepted for sensor_type="boolean" (HA uses on/off)
_TRUE_VALUES = {"true", "on", "1", "yes"}
_FALSE_VALUES = {"false", "off", "0", "no"}


def decode_value(sensor_type: str, raw: str):
    """Decode a stored text value per the sensor's declared type.

    Returns (value, ok). On failure value is None and ok is False.
    """
    if sensor_type == "numeric":
        try:
            return float(raw), True
        except (TypeError, ValueError):
            return None, False
    if sensor_type == "boolean":
        lowered = raw.strip().lower()
        if lowered in _TRUE_VALUES:
            return True, True
        if lowered in _FALSE_VALUES:
            return False, True
        return None, False
    return raw, True


def _as_utc(dt: datetime) -> datetime:
    """SQLite hands back naive datetimes; column semantics are UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def _resolve_sensors(
    db: AsyncSession, names: Sequence[str], autoregister: bool
) -> dict[str, Sensor]:
    """Map sensor names to Sensor rows, optionally creating missing ones."""
    unique_names = list(dict.fromkeys(names))
    result = await db.execute(select(Sensor).where(Sensor.name.in_(unique_names)))
    by_name = {s.name: s for s in result.scalars()}

    if autoregister:
        for name in unique_names:
            if name not in by_name:
                sensor = Sensor(
                    name=name,
                    sensor_type="numeric",
                    description="auto-registered from ingest",
                )
                db.add(sensor)
                by_name[name] = sensor
        await db.flush()  # assign ids for the new sensors

    return by_name


async def ingest_measurements(db: AsyncSession, payload: IngestRequest) -> IngestResponse:
    """Idempotent batch ingest with per-row validation.

    Bad rows are reported in ``skipped_invalid`` and never poison the batch;
    duplicates of (sensor, timestamp) update the stored value in place.
    """
    skipped: list[IngestSkipped] = []
    valid_rows = []

    for index, row in enumerate(payload.measurements):
        if row.value.strip().lower() in NON_VALUES:
            skipped.append(IngestSkipped(index=index, reason=f"non-value state {row.value!r}"))
            continue
        valid_rows.append((index, row))

    if not valid_rows:
        return IngestResponse(accepted=0, created=0, updated=0, skipped_invalid=skipped)

    sensors = await _resolve_sensors(
        db, [row.sensor for _, row in valid_rows], autoregister=True
    )

    # Which (sensor_id, timestamp) pairs already exist? Needed only to report
    # created-vs-updated counts; the upsert itself handles both cases.
    pairs = [(sensors[row.sensor].id, row.timestamp) for _, row in valid_rows]
    sensor_ids = list({sid for sid, _ in pairs})
    timestamps = list({ts for _, ts in pairs})
    result = await db.execute(
        select(Measurement.sensor_id, Measurement.timestamp).where(
            Measurement.sensor_id.in_(sensor_ids),
            Measurement.timestamp.in_(timestamps),
        )
    )
    existing = {(sid, _as_utc(ts)) for sid, ts in result.all()}

    created = updated = 0
    # Deduplicate rows inside the batch (last one wins) so a single INSERT
    # never conflicts with itself.
    deduped: dict[tuple[int, datetime], dict] = {}
    for _, row in valid_rows:
        sensor_id = sensors[row.sensor].id
        deduped[(sensor_id, row.timestamp)] = {
            "sensor_id": sensor_id,
            "timestamp": row.timestamp,
            "value": row.value,
            "source": payload.source,
        }

    for key in deduped:
        if key in existing:
            updated += 1
        else:
            created += 1

    stmt = sqlite_insert(Measurement).values(list(deduped.values()))
    stmt = stmt.on_conflict_do_update(
        index_elements=["sensor_id", "timestamp"],
        set_={"value": stmt.excluded.value, "source": stmt.excluded.source},
    )
    await db.execute(stmt)
    await db.commit()

    return IngestResponse(
        accepted=len(deduped),
        created=created,
        updated=updated,
        skipped_invalid=skipped,
    )


async def get_series(
    db: AsyncSession,
    sensor_names: Sequence[str],
    start: Optional[datetime],
    end: Optional[datetime],
    page: int,
    page_size: int,
    ascending: bool = True,
) -> tuple[list[SensorSeries], int]:
    """Typed, paginated series for the requested sensors.

    Pagination applies to the combined row stream ordered by timestamp,
    so pages are stable across sensors.
    """
    result = await db.execute(select(Sensor).where(Sensor.name.in_(list(sensor_names))))
    sensors = {s.id: s for s in result.scalars()}
    if not sensors:
        return [], 0

    filters = [Measurement.sensor_id.in_(list(sensors))]
    if start is not None:
        filters.append(Measurement.timestamp >= start)
    if end is not None:
        filters.append(Measurement.timestamp < end)

    total = (
        await db.execute(select(func.count()).select_from(Measurement).where(*filters))
    ).scalar_one()

    order = (
        (Measurement.timestamp.asc(), Measurement.sensor_id.asc())
        if ascending
        else (Measurement.timestamp.desc(), Measurement.sensor_id.desc())
    )
    result = await db.execute(
        select(Measurement)
        .where(*filters)
        .order_by(*order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    series: dict[int, SensorSeries] = {}
    for m in result.scalars():
        sensor = sensors[m.sensor_id]
        bucket = series.setdefault(
            sensor.id,
            SensorSeries(sensor=sensor.name, unit=sensor.unit, type=sensor.sensor_type, points=[]),
        )
        value, ok = decode_value(sensor.sensor_type, m.value)
        point = SeriesPoint(t=_as_utc(m.timestamp), v=value)
        if not ok:
            point.raw = m.value
        bucket.points.append(point)

    # Keep the caller's sensor order
    ordered = [
        series[s.id] for s in sensors.values() if s.id in series
    ]
    return ordered, total


async def get_current_values(
    db: AsyncSession, sensor_names: Sequence[str]
) -> list[CurrentValue]:
    """Latest value per requested sensor; unknown sensors yield value=None."""
    result = await db.execute(select(Sensor).where(Sensor.name.in_(list(sensor_names))))
    by_name = {s.name: s for s in result.scalars()}

    now = datetime.now(timezone.utc)
    values: list[CurrentValue] = []
    for name in dict.fromkeys(sensor_names):
        sensor = by_name.get(name)
        if sensor is None:
            values.append(CurrentValue(sensor=name))
            continue
        latest = (
            await db.execute(
                select(Measurement)
                .where(Measurement.sensor_id == sensor.id)
                .order_by(Measurement.timestamp.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest is None:
            values.append(CurrentValue(sensor=name, unit=sensor.unit))
            continue
        value, _ = decode_value(sensor.sensor_type, latest.value)
        ts = _as_utc(latest.timestamp)
        values.append(
            CurrentValue(
                sensor=name,
                value=value,
                unit=sensor.unit,
                timestamp=ts,
                age_seconds=max(0, int((now - ts).total_seconds())),
            )
        )
    return values
