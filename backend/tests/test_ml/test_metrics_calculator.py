"""Tests for metrics calculator against the real ground-truth path."""
import pytest
from datetime import date, datetime, timedelta, timezone

from app.ml.metrics_calculator import MetricsCalculator, GROUND_TRUTH_SENSOR
from app.models import Measurement, Sensor
from app.models.ml import Prediction, MLModel

TARGET_DATE = date(2026, 8, 20)
DAY_START = datetime.combine(TARGET_DATE, datetime.min.time(), tzinfo=timezone.utc)


async def make_model(db_session, name="test_model") -> MLModel:
    model = MLModel(name=name, version="1.0.0", config={"threshold": 0.5}, active=True)
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    return model


async def seed_predictions(db_session, model_id, probs_and_binaries):
    db_session.add_all([
        Prediction(
            model_id=model_id,
            timestamp=DAY_START + timedelta(hours=i),
            probability=prob,
            binary_prediction=binary,
            threshold=0.5,
        )
        for i, (prob, binary) in enumerate(probs_and_binaries)
    ])
    await db_session.commit()


async def seed_ground_truth(db_session, hourly_precip):
    sensor = Sensor(name=GROUND_TRUTH_SENSOR, unit="mm", sensor_type="numeric")
    db_session.add(sensor)
    await db_session.flush()
    db_session.add_all([
        Measurement(
            sensor_id=sensor.id,
            timestamp=DAY_START + timedelta(hours=i),
            value=str(precip),
            source="test",
        )
        for i, precip in enumerate(hourly_precip)
    ])
    await db_session.commit()


@pytest.mark.asyncio
async def test_no_predictions_returns_none(db_session):
    calculator = MetricsCalculator(db_session)
    assert await calculator.calculate_daily_metrics(999, TARGET_DATE) is None


@pytest.mark.asyncio
async def test_no_ground_truth_returns_none(db_session):
    model = await make_model(db_session)
    await seed_predictions(db_session, model.id, [(0.5, True)] * 8)

    calculator = MetricsCalculator(db_session)
    assert await calculator.calculate_daily_metrics(model.id, TARGET_DATE) is None


@pytest.mark.asyncio
async def test_fetch_ground_truth_reads_measurements(db_session):
    await seed_ground_truth(db_session, [0.0, 0.0, 1.2, 0.4, 0.0])

    calculator = MetricsCalculator(db_session)
    truth = await calculator._fetch_ground_truth(TARGET_DATE)

    assert truth is not None
    assert truth[DAY_START] == 0
    assert truth[DAY_START + timedelta(hours=2)] == 1
    assert truth[DAY_START + timedelta(hours=3)] == 1
    assert len(truth) == 5


@pytest.mark.asyncio
async def test_too_few_matched_hours_returns_none(db_session):
    model = await make_model(db_session)
    await seed_predictions(db_session, model.id, [(0.7, True)] * 3)
    await seed_ground_truth(db_session, [1.0, 1.0, 1.0])

    calculator = MetricsCalculator(db_session)
    # 3 matched hours < MIN_MATCHED_HOURS
    assert await calculator.calculate_daily_metrics(model.id, TARGET_DATE) is None


@pytest.mark.asyncio
async def test_metrics_computed_correctly(db_session):
    model = await make_model(db_session)
    # 8 hours: predictions perfect for first 6, wrong for last 2
    probs = [(0.9, True), (0.8, True), (0.1, False), (0.2, False),
             (0.9, True), (0.1, False), (0.9, True), (0.2, False)]
    truth = [1.0, 0.5, 0.0, 0.0, 2.0, 0.0, 0.0, 1.0]  # rain hours: 0,1,4,7
    await seed_predictions(db_session, model.id, probs)
    await seed_ground_truth(db_session, truth)

    calculator = MetricsCalculator(db_session)
    metrics = await calculator.calculate_daily_metrics(model.id, TARGET_DATE)

    assert metrics is not None
    # y_true = [1,1,0,0,1,0,0,1], y_pred = [1,1,0,0,1,0,1,0]
    # TP=3 FP=1 FN=1 TN=3
    assert metrics["confusion_matrix"] == {"TN": 3, "FP": 1, "FN": 1, "TP": 3}
    assert metrics["precision"] == pytest.approx(0.75)
    assert metrics["recall"] == pytest.approx(0.75)
    assert metrics["f1_score"] == pytest.approx(0.75)
    assert metrics["threshold"] == 0.5
    assert 0 <= metrics["brier_score"] <= 1
    assert metrics["calibration_slope"] is not None


@pytest.mark.asyncio
async def test_single_class_day_has_no_calibration_slope(db_session):
    model = await make_model(db_session)
    await seed_predictions(db_session, model.id, [(0.1, False)] * 8)
    await seed_ground_truth(db_session, [0.0] * 8)  # fully dry day

    calculator = MetricsCalculator(db_session)
    metrics = await calculator.calculate_daily_metrics(model.id, TARGET_DATE)

    assert metrics is not None
    assert metrics["calibration_slope"] is None
    assert metrics["confusion_matrix"]["TN"] == 8
