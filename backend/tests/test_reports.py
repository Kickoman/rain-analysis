"""Tests for Report model"""
import pytest
from datetime import date, datetime
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, inspect
from app.models.report import Report


@pytest.mark.asyncio
async def test_report_creation(db_session):
    """Test Report can be created with required fields"""
    report = Report(
        date=date(2026, 7, 22),
        content={
            "date": "2026-07-22",
            "models": [
                {
                    "name": "pressure_primary",
                    "metrics": {"7d": {"f1": 0.435, "precision": 0.357, "recall": 0.556}}
                }
            ]
        },
        meta={"source": "markdown_migration"}
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    assert report.id is not None
    assert report.date == date(2026, 7, 22)
    assert report.content["date"] == "2026-07-22"
    assert report.meta["source"] == "markdown_migration"
    assert report.created_at is not None
    assert report.updated_at is not None


@pytest.mark.asyncio
async def test_report_unique_date(db_session):
    """Test Report date must be unique"""
    report1 = Report(
        date=date(2026, 7, 23),
        content={"date": "2026-07-23", "models": []}
    )
    db_session.add(report1)
    await db_session.commit()

    report2 = Report(
        date=date(2026, 7, 23),
        content={"date": "2026-07-23", "models": []}
    )
    db_session.add(report2)

    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_report_json_serialization(db_session):
    """Test JSON content and meta fields serialize/deserialize correctly"""
    content = {
        "date": "2026-07-24",
        "executive_summary": {
            "best_overall_f2": {"model": "pressure_primary", "window": "7d"},
            "key_findings": ["best model varies by window"],
        },
        "data_context": {
            "ground_truth_source": "open-meteo",
            "coverage": {"home_assistant": 0.994, "open_meteo": 1.0},
            "distribution": {"rain_hours": 9, "dry_hours": 161},
        },
        "models": [
            {
                "name": "pressure_primary",
                "status": "📊",
                "metrics": {"7d": {"f1": 0.435, "precision": 0.357, "recall": 0.556}},
            }
        ],
        "multi_window_comparison": {
            "f2_scores": [{"model": "pressure_primary", "7d": None, "14d": 0.39, "28d": 0.39}],
        },
        "temporal_metrics": [
            {"model": "pressure_primary", "f1": 0.947, "best_threshold": "55%", "window": "7d"}
        ],
    }

    meta = {
        "source": "markdown_migration",
        "original_file": "reports/2026-07-24.md",
        "migrated_at": "2026-07-25T00:15:00Z",
    }

    report = Report(date=date(2026, 7, 24), content=content, meta=meta)
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    # Verify complex JSON structure is preserved
    assert report.content["models"][0]["name"] == "pressure_primary"
    assert report.content["models"][0]["metrics"]["7d"]["f1"] == 0.435
    assert report.content["multi_window_comparison"]["f2_scores"][0]["7d"] is None
    assert report.meta["original_file"] == "reports/2026-07-24.md"


@pytest.mark.asyncio
async def test_report_meta_optional(db_session):
    """Test Report can be created without meta field"""
    report = Report(
        date=date(2026, 7, 25),
        content={"date": "2026-07-25", "models": []}
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    assert report.meta is None


@pytest.mark.asyncio
async def test_report_source_markdown(db_session):
    """Test source_markdown stores raw markdown for reversibility"""
    markdown = "# Daily Model Analysis — 2026-07-26\n\n## Model Performance (7-day window)\n..."
    report = Report(
        date=date(2026, 7, 26),
        content={"date": "2026-07-26", "models": []},
        source_markdown=markdown,
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    assert report.source_markdown == markdown

    # And it's optional (migrated/API-generated reports may omit it)
    report2 = Report(
        date=date(2026, 7, 27),
        content={"date": "2026-07-27", "models": []},
    )
    db_session.add(report2)
    await db_session.commit()
    await db_session.refresh(report2)
    assert report2.source_markdown is None


@pytest.mark.asyncio
async def test_report_date_index(db_session):
    """Test that reports.date has a unique index for efficient date queries"""
    conn = await db_session.connection()
    indexes = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_indexes("reports"))
    date_indexes = [ix for ix in indexes if ix["column_names"] == ["date"]]

    assert len(date_indexes) == 1, f"Expected exactly one date index, got {date_indexes}"
    assert date_indexes[0]["name"] == "ix_reports_date"
    assert date_indexes[0]["unique"], "Expected reports.date index to be unique"


@pytest.mark.asyncio
async def test_report_date_range_query(db_session):
    """Test Reports can be queried by date range"""
    # Create reports
    for day in range(20, 28):
        report = Report(
            date=date(2026, 7, day),
            content={"date": f"2026-07-{day}", "models": []}
        )
        db_session.add(report)
    await db_session.commit()

    # Query date range
    stmt = select(Report).where(
        Report.date >= date(2026, 7, 22),
        Report.date <= date(2026, 7, 25)
    ).order_by(Report.date.desc())
    result = await db_session.execute(stmt)
    reports = result.scalars().all()

    assert len(reports) == 4
    assert reports[0].date == date(2026, 7, 25)
    assert reports[3].date == date(2026, 7, 22)
