"""Report upsert and query logic (single upsert path, per #232 review)."""

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Report
from ..schemas.report import ReportSummary, ReportUpsertRequest


def _best_model(content: dict) -> Optional[str]:
    summary = content.get("executive_summary") or {}
    return summary.get("best_model")


async def upsert_report(db: AsyncSession, payload: ReportUpsertRequest) -> str:
    """Insert or overwrite the report for a date. Returns "created"/"updated".

    Overwrites are how backfilled regenerations land (#429): the row keeps
    its identity, `updated_at` records the overwrite.
    """
    existing = (
        await db.execute(select(Report).where(Report.report_date == payload.report_date))
    ).scalar_one_or_none()

    content = payload.content.model_dump(exclude_none=True)

    if existing is None:
        db.add(Report(
            report_date=payload.report_date,
            content=content,
            meta=payload.meta,
        ))
        action = "created"
    else:
        existing.content = content
        existing.meta = payload.meta if payload.meta is not None else existing.meta
        existing.updated_at = datetime.now(timezone.utc)
        action = "updated"

    await db.commit()
    return action


async def get_report(db: AsyncSession, report_date: date) -> Optional[Report]:
    return (
        await db.execute(select(Report).where(Report.report_date == report_date))
    ).scalar_one_or_none()


async def get_latest_report(db: AsyncSession) -> Optional[Report]:
    return (
        await db.execute(select(Report).order_by(Report.report_date.desc()).limit(1))
    ).scalar_one_or_none()


async def list_reports(
    db: AsyncSession,
    start: Optional[date],
    end: Optional[date],
    page: int,
    page_size: int,
) -> tuple[list[ReportSummary], int]:
    filters = []
    if start is not None:
        filters.append(Report.report_date >= start)
    if end is not None:
        filters.append(Report.report_date <= end)

    total = (
        await db.execute(select(func.count()).select_from(Report).where(*filters))
    ).scalar_one()

    rows = (
        await db.execute(
            select(Report)
            .where(*filters)
            .order_by(Report.report_date.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    summaries = [
        ReportSummary(
            report_date=r.report_date,
            best_model=_best_model(r.content or {}),
            executive_summary=(r.content or {}).get("executive_summary"),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    return summaries, total
