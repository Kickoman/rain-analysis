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
                    "name": "baseline",
                    "metrics": {"f2": 0.72, "precision": 0.65, "recall": 0.80}
                }
            ]
        },
        meta={"model_versions": {"baseline": "1.0.0"}}
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)
    
    assert report.id is not None
    assert report.date == date(2026, 7, 22)
    assert report.content["date"] == "2026-07-22"
    assert report.meta["model_versions"]["baseline"] == "1.0.0"
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
        "models": [
            {
                "name": "baseline",
                "version": "1.0.0",
                "metrics": {"f2": 0.72, "precision": 0.65, "recall": 0.80},
                "predictions": [
                    {
                        "timestamp": "2026-07-24T00:00:00Z",
                        "rain_prob": 0.3,
                        "rain_pred": False
                    }
                ]
            }
        ],
        "weather_summary": {
            "avg_temp": 22.5,
            "avg_humidity": 65.0
        },
        "charts_data": {
            "predictions_timeline": [
                {"x": "2026-07-24T00:00:00Z", "y": 0.3}
            ]
        }
    }
    
    meta = {
        "model_versions": {"baseline": "1.0.0"},
        "data_coverage": 0.95,
        "generation_time": "2026-07-25T00:15:00Z"
    }
    
    report = Report(date=date(2026, 7, 24), content=content, meta=meta)
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)
    
    # Verify complex JSON structure is preserved
    assert report.content["models"][0]["name"] == "baseline"
    assert report.content["models"][0]["predictions"][0]["rain_prob"] == 0.3
    assert report.content["weather_summary"]["avg_temp"] == 22.5
    assert report.meta["data_coverage"] == 0.95


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
