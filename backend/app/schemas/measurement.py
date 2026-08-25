from pydantic import BaseModel, Field, ConfigDict, field_validator
from datetime import datetime, timezone
from typing import Optional, Any
from .base import IDMixin


class MeasurementBase(BaseModel):
    """Base schema for Measurement."""
    sensor_id: int
    timestamp: datetime
    value: Any
    source: str = Field(default="manual", max_length=50)


class MeasurementCreate(MeasurementBase):
    """Schema for creating a new Measurement."""
    pass


class MeasurementResponse(MeasurementBase, IDMixin):
    """Schema for Measurement response."""
    model_config = ConfigDict(from_attributes=True)


class MeasurementBulkCreate(BaseModel):
    """Schema for bulk creating Measurements."""
    measurements: list[MeasurementCreate]


# --- Data API (ingest + typed series) -------------------------------------

SENSOR_NAME_PATTERN = r"^[a-z0-9_.]+$"

# Home Assistant states that mean "no value" and must not be stored
NON_VALUES = {"unknown", "unavailable", "none", ""}

MAX_INGEST_BATCH = 1000


class IngestMeasurement(BaseModel):
    """One measurement row pushed by a client (e.g. Home Assistant)."""
    sensor: str = Field(..., min_length=1, max_length=128, pattern=SENSOR_NAME_PATTERN)
    timestamp: datetime
    value: str = Field(..., max_length=1024)

    @field_validator("timestamp")
    @classmethod
    def normalize_to_utc(cls, v: datetime) -> datetime:
        """Store everything in UTC so (sensor, timestamp) uniqueness holds."""
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @field_validator("value", mode="before")
    @classmethod
    def coerce_value_to_str(cls, v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        return v


class IngestRequest(BaseModel):
    """Batch ingest payload."""
    source: str = Field(default="api", max_length=50)
    measurements: list[IngestMeasurement] = Field(..., min_length=1, max_length=MAX_INGEST_BATCH)


class IngestSkipped(BaseModel):
    """A row rejected during ingest, with the reason."""
    index: int
    reason: str


class IngestResponse(BaseModel):
    """Result of a batch ingest: partial acceptance, never all-or-nothing."""
    accepted: int
    created: int
    updated: int
    skipped_invalid: list[IngestSkipped] = []


class SeriesPoint(BaseModel):
    """One decoded point of a series."""
    t: datetime
    v: Optional[Any] = None
    raw: Optional[str] = None  # set only when decoding failed


class SensorSeries(BaseModel):
    """A typed series for one sensor."""
    sensor: str
    unit: Optional[str] = None
    type: str
    points: list[SeriesPoint]


class MeasurementSeriesResponse(BaseModel):
    """Paginated typed series for one or more sensors."""
    series: list[SensorSeries]
    page: int
    page_size: int
    total: int


class CurrentValue(BaseModel):
    """Latest value of one sensor (widget endpoint)."""
    sensor: str
    value: Optional[Any] = None
    unit: Optional[str] = None
    timestamp: Optional[datetime] = None
    age_seconds: Optional[int] = None


class CurrentValuesResponse(BaseModel):
    """Latest values for the requested sensors."""
    values: list[CurrentValue]
