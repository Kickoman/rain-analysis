"""Tests for ML models (MLModel, Prediction, ModelMetric)"""
import pytest
from datetime import datetime, date
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from app.models.ml import MLModel, Prediction, ModelMetric


@pytest.mark.asyncio
async def test_ml_model_creation(db_session):
    """Test MLModel can be created with required fields"""
    model = MLModel(
        name="test_model",
        version="1.0.0",
        description="Test model for unit tests",
        config={"features": ["temp", "humidity"], "hyperparameters": {"lr": 0.01}},
        active=True
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    
    assert model.id is not None
    assert model.name == "test_model"
    assert model.active is True
    assert model.created_at is not None


@pytest.mark.asyncio
async def test_ml_model_unique_name(db_session):
    """Test MLModel name must be unique"""
    model1 = MLModel(name="duplicate_model", version="1.0")
    db_session.add(model1)
    await db_session.commit()
    
    model2 = MLModel(name="duplicate_model", version="2.0")
    db_session.add(model2)
    
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_prediction_creation(db_session):
    """Test Prediction can be created with required fields"""
    model = MLModel(name="pred_test_model", version="1.0")
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    
    prediction = Prediction(
        model_id=model.id,
        timestamp=datetime(2024, 1, 1, 12, 0),
        probability=0.75,
        threshold=0.5,
        binary_prediction=True
    )
    db_session.add(prediction)
    await db_session.commit()
    await db_session.refresh(prediction)
    
    assert prediction.id is not None
    assert prediction.probability == 0.75
    assert prediction.binary_prediction is True


@pytest.mark.asyncio
async def test_prediction_unique_model_timestamp(db_session):
    """Test Prediction must have unique (model_id, timestamp)"""
    model = MLModel(name="unique_pred_model", version="1.0")
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    
    ts = datetime(2024, 1, 1, 12, 0)
    pred1 = Prediction(model_id=model.id, timestamp=ts, probability=0.5)
    db_session.add(pred1)
    await db_session.commit()
    
    pred2 = Prediction(model_id=model.id, timestamp=ts, probability=0.6)
    db_session.add(pred2)
    
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_prediction_relationship(db_session):
    """Test Prediction <-> MLModel relationship"""
    model = MLModel(name="relationship_model", version="1.0")
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    
    pred1 = Prediction(model_id=model.id, timestamp=datetime(2024, 1, 1), probability=0.3)
    pred2 = Prediction(model_id=model.id, timestamp=datetime(2024, 1, 2), probability=0.7)
    db_session.add_all([pred1, pred2])
    await db_session.commit()
    
    # Refresh to load relationships
    await db_session.refresh(model, ["predictions"])
    await db_session.refresh(pred1, ["model"])
    
    assert len(model.predictions) == 2
    assert pred1.model.name == "relationship_model"


@pytest.mark.asyncio
async def test_model_metric_creation(db_session):
    """Test ModelMetric can be created with all fields"""
    model = MLModel(name="metric_test_model", version="1.0")
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    
    metric = ModelMetric(
        model_id=model.id,
        date=date(2024, 1, 1),
        brier_score=0.15,
        f1_score=0.85,
        f2_score=0.82,
        precision_score=0.90,
        recall=0.80,
        calibration_slope=1.05,
        threshold=0.5,
        confusion_matrix={"TP": 40, "FP": 5, "FN": 10, "TN": 45}
    )
    db_session.add(metric)
    await db_session.commit()
    await db_session.refresh(metric)
    
    assert metric.id is not None
    assert metric.f1_score == 0.85
    assert metric.confusion_matrix["TP"] == 40


@pytest.mark.asyncio
async def test_model_metric_unique_model_date(db_session):
    """Test ModelMetric must have unique (model_id, date)"""
    model = MLModel(name="unique_metric_model", version="1.0")
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    
    metric_date = date(2024, 1, 1)
    metric1 = ModelMetric(model_id=model.id, date=metric_date, f1_score=0.8)
    db_session.add(metric1)
    await db_session.commit()
    
    metric2 = ModelMetric(model_id=model.id, date=metric_date, f1_score=0.9)
    db_session.add(metric2)
    
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_model_metric_relationship(db_session):
    """Test ModelMetric <-> MLModel relationship"""
    model = MLModel(name="metric_rel_model", version="1.0")
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    
    metric1 = ModelMetric(model_id=model.id, date=date(2024, 1, 1), f1_score=0.8)
    metric2 = ModelMetric(model_id=model.id, date=date(2024, 1, 2), f1_score=0.85)
    db_session.add_all([metric1, metric2])
    await db_session.commit()
    
    # Refresh to load relationships
    await db_session.refresh(model, ["metrics"])
    await db_session.refresh(metric1, ["model"])
    
    assert len(model.metrics) == 2
    assert metric1.model.name == "metric_rel_model"


@pytest.mark.asyncio
async def test_cascade_delete_predictions(db_session):
    """Test deleting MLModel cascades to predictions"""
    model = MLModel(name="cascade_model", version="1.0")
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    
    pred = Prediction(model_id=model.id, timestamp=datetime(2024, 1, 1), probability=0.5)
    db_session.add(pred)
    await db_session.commit()
    
    model_id = model.id
    await db_session.delete(model)
    await db_session.commit()
    
    # Prediction should be deleted
    result = await db_session.execute(select(Prediction).filter_by(model_id=model_id))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_cascade_delete_metrics(db_session):
    """Test deleting MLModel cascades to metrics"""
    model = MLModel(name="cascade_metric_model", version="1.0")
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    
    metric = ModelMetric(model_id=model.id, date=date(2024, 1, 1), f1_score=0.8)
    db_session.add(metric)
    await db_session.commit()
    
    model_id = model.id
    await db_session.delete(model)
    await db_session.commit()
    
    # Metric should be deleted
    result = await db_session.execute(select(ModelMetric).filter_by(model_id=model_id))
    assert result.scalar_one_or_none() is None
