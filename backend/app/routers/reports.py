"""Reports API (Phase 4, #396-#403). The pipeline POSTs finished reports
(variant B — the backend never generates them)."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_api_key
from ..database import get_db
from ..models import APIKey
from ..schemas.report import (
    ReportListResponse,
    ReportResponse,
    ReportUpsertRequest,
    ReportUpsertResponse,
)
from ..services import report_service

router = APIRouter(prefix="/reports", tags=["reports"])


def _to_response(report, include_markdown: bool) -> ReportResponse:
    meta = report.meta
    if meta and not include_markdown and "source_markdown" in meta:
        meta = {k: v for k, v in meta.items() if k != "source_markdown"}
    return ReportResponse(
        id=report.id,
        report_date=report.report_date,
        content=report.content,
        meta=meta,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


@router.post("", response_model=ReportUpsertResponse)
async def upsert_report(
    payload: ReportUpsertRequest,
    api_key: APIKey = Depends(require_api_key("write")),
    db: AsyncSession = Depends(get_db),
):
    """Insert or overwrite the report for a date (idempotent by report_date)."""
    action = await report_service.upsert_report(db, payload)
    return ReportUpsertResponse(report_date=payload.report_date, action=action)


@router.get("", response_model=ReportListResponse)
async def list_reports(
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    api_key: APIKey = Depends(require_api_key("read")),
    db: AsyncSession = Depends(get_db),
):
    """Paginated report summaries, newest first."""
    summaries, total = await report_service.list_reports(db, start, end, page, page_size)
    return ReportListResponse(reports=summaries, total=total, page=page, page_size=page_size)


@router.get("/latest", response_model=ReportResponse)
async def latest_report(
    include_markdown: bool = Query(False),
    api_key: APIKey = Depends(require_api_key("read")),
    db: AsyncSession = Depends(get_db),
):
    """The most recent report."""
    report = await report_service.get_latest_report(db)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No reports stored")
    return _to_response(report, include_markdown)


@router.get("/{report_date}", response_model=ReportResponse)
async def get_report(
    report_date: date,
    include_markdown: bool = Query(False, description="Embed meta.source_markdown (large)"),
    api_key: APIKey = Depends(require_api_key("read")),
    db: AsyncSession = Depends(get_db),
):
    """Full report for one date."""
    report = await report_service.get_report(db, report_date)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No report for {report_date}",
        )
    return _to_response(report, include_markdown)
