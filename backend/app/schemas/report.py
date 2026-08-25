"""Report schemas — the content structure agreed in #232.

Every content section is optional-tolerant: migrated reports carry only the
sections their markdown had, and new sections can be added without breaking
old rows. `predictions`, `weather_summary` and `charts_data` exist in the
shape but are not populated for migrated reports.
"""

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ModelMetricsEntry(BaseModel):
    """Leaderboard row for one model."""
    name: str
    metrics: dict[str, Optional[float]] = Field(default_factory=dict)
    status: Optional[str] = None


class ReportContent(BaseModel):
    """Structured content of a daily report (#232 schema)."""
    executive_summary: Optional[dict[str, Any]] = None
    data_context: Optional[dict[str, Any]] = None
    models: Optional[list[ModelMetricsEntry]] = None
    multi_window_comparison: Optional[dict[str, Any]] = None
    rankings: Optional[dict[str, Any]] = None
    temporal_metrics: Optional[dict[str, Any]] = None
    precipitation_source_reliability: Optional[dict[str, Any]] = None
    # Present in the shape, not populated for migrated reports (#232)
    predictions: Optional[dict[str, Any]] = None
    weather_summary: Optional[dict[str, Any]] = None
    charts_data: Optional[dict[str, Any]] = None


class ReportUpsertRequest(BaseModel):
    """POST /reports payload — upserts by report_date."""
    report_date: date
    content: ReportContent
    meta: Optional[dict[str, Any]] = None


class ReportResponse(BaseModel):
    """Full report."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_date: date
    content: dict[str, Any]
    meta: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class ReportSummary(BaseModel):
    """List projection: date plus the headline facts."""
    report_date: date
    best_model: Optional[str] = None
    executive_summary: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class ReportListResponse(BaseModel):
    reports: list[ReportSummary]
    total: int
    page: int
    page_size: int


class ReportUpsertResponse(BaseModel):
    report_date: date
    action: str  # "created" | "updated"
