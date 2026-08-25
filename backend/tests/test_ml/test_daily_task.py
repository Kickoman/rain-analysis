"""Tests for the daily ML task against the measurements-backed feature path."""
import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pandas as pd
from sqlalchemy import select

from app.ml.daily_task import DailyMLTask
from app.models import Measurement, Sensor
from app.models.ml import MLModel, ModelMetric, Prediction

TARGET_DATE = date(2026, 8, 20)
DAY_START = datetime.combine(TARGET_DATE, datetime.min.time(), tzinfo=timezone.utc)

SENSOR_MAP = {"spread": "sensor.spread", "pressure": "sensor.pressure"}


async def make_model(db_session, name="test_model", config=None) -> MLModel:
    model = MLModel(
        name=name,
        version="1.0.0",
        description="Test model",
        config=config or {"kind": "rainlib", "rainlib_model": "ha_live",
                          "threshold": 0.5, "sensor_map": SENSOR_MAP},
        active=True,
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    return model


async def seed_measurements(db_session, sensor_name, hourly_values):
    sensor = Sensor(name=sensor_name, sensor_type="numeric")
    db_session.add(sensor)
    await db_session.flush()
    db_session.add_all([
        Measurement(
            sensor_id=sensor.id,
            timestamp=DAY_START + timedelta(hours=i),
            value=str(v),
            source="test",
        )
        for i, v in enumerate(hourly_values)
        if v is not None
    ])
    await db_session.commit()


@pytest.mark.asyncio
async def test_daily_task_no_active_models(db_session):
    """Task exits gracefully when no active models exist."""
    await DailyMLTask().run(db=db_session, target_date=TARGET_DATE)


@pytest.mark.asyncio
async def test_daily_task_no_sensor_map(db_session):
    """Task exits gracefully when models declare no sensor_map."""
    await make_model(db_session, config={"threshold": 0.5})
    await DailyMLTask().run(db=db_session, target_date=TARGET_DATE)


@pytest.mark.asyncio
async def test_daily_task_no_weather_data(db_session):
    """Task exits gracefully when the day has no measurements."""
    await make_model(db_session)
    await DailyMLTask().run(db=db_session, target_date=TARGET_DATE)
    rows = (await db_session.execute(select(Prediction))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_fetch_weather_data_pivots_hourly(db_session):
    await seed_measurements(db_session, "sensor.spread", [5.0, 4.0, None, None, None, 2.0])
    await seed_measurements(db_session, "sensor.pressure", [990.0] * 6)

    task = DailyMLTask()
    wide = await task._fetch_weather_data(
        db_session, TARGET_DATE, ["sensor.spread", "sensor.pressure"]
    )

    assert list(wide.columns) == ["sensor.pressure", "sensor.spread"]
    assert isinstance(wide.index, pd.DatetimeIndex)
    # ffill bridges up to 2 missing hours, hour 4 stays NaN
    assert wide["sensor.spread"].iloc[2] == 4.0
    assert wide["sensor.spread"].iloc[3] == 4.0
    assert pd.isna(wide["sensor.spread"].iloc[4])


@pytest.mark.asyncio
async def test_daily_task_end_to_end_rainlib(db_session):
    """Full path: measurements -> features -> rainlib model -> stored predictions."""
    await make_model(db_session)
    await seed_measurements(db_session, "sensor.spread", [5.0, 3.0, 1.0, 0.5] * 6)
    await seed_measurements(db_session, "sensor.pressure", [995.0] * 24)

    await DailyMLTask().run(db=db_session, target_date=TARGET_DATE)

    rows = (await db_session.execute(select(Prediction))).scalars().all()
    assert len(rows) == 24
    assert all(0.0 <= p.probability <= 1.0 for p in rows)

    # Re-run is an upsert, not a duplicate
    await DailyMLTask().run(db=db_session, target_date=TARGET_DATE)
    rows = (await db_session.execute(select(Prediction))).scalars().all()
    assert len(rows) == 24


@pytest.mark.asyncio
async def test_daily_task_model_error_continues(db_session):
    """An error in one model must not stop the others."""
    await make_model(db_session, name="broken",
                     config={"kind": "sklearn", "file_path": "missing.pkl",
                             "threshold": 0.5, "sensor_map": SENSOR_MAP})
    await make_model(db_session, name="working")
    await seed_measurements(db_session, "sensor.spread", [5.0] * 24)
    await seed_measurements(db_session, "sensor.pressure", [995.0] * 24)

    await DailyMLTask().run(db=db_session, target_date=TARGET_DATE)

    working = (
        await db_session.execute(select(MLModel).where(MLModel.name == "working"))
    ).scalar_one()
    rows = (
        await db_session.execute(select(Prediction).where(Prediction.model_id == working.id))
    ).scalars().all()
    assert len(rows) == 24


@pytest.mark.asyncio
async def test_daily_task_metrics_storage(db_session):
    """Metrics returned by the calculator are upserted into model_metrics."""
    model = await make_model(db_session)
    await seed_measurements(db_session, "sensor.spread", [5.0] * 24)
    await seed_measurements(db_session, "sensor.pressure", [995.0] * 24)

    mock_metrics = {
        "brier_score": 0.25, "f1_score": 0.85, "f2_score": 0.88,
        "precision": 0.80, "recall": 0.90, "threshold": 0.5,
        "calibration_slope": 1.1,
        "confusion_matrix": {"TP": 10, "TN": 8, "FP": 2, "FN": 1},
    }
    with patch("app.ml.daily_task.MetricsCalculator") as MockCalculator:
        MockCalculator.return_value.calculate_daily_metrics = AsyncMock(return_value=mock_metrics)
        await DailyMLTask().run(db=db_session, target_date=TARGET_DATE)
        # Second run exercises the metric upsert path
        await DailyMLTask().run(db=db_session, target_date=TARGET_DATE)

    records = (
        await db_session.execute(select(ModelMetric).where(ModelMetric.model_id == model.id))
    ).scalars().all()
    assert len(records) == 1
    assert records[0].date == TARGET_DATE
    assert records[0].brier_score == 0.25
    assert records[0].f2_score == 0.88
