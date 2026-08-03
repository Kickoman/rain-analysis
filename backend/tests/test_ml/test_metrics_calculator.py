"""Tests for metrics calculator."""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.ml.metrics_calculator import MetricsCalculator
from app.models.ml import Prediction, MLModel


@pytest.mark.asyncio
async def test_calculate_daily_metrics_no_predictions(db_session):
    """Test metrics calculation when no predictions exist."""
    calculator = MetricsCalculator(db_session)
    
    target_date = date.today() - timedelta(days=1)
    result = await calculator.calculate_daily_metrics(model_id=999, target_date=target_date)
    
    assert result is None


@pytest.mark.asyncio
async def test_calculate_daily_metrics_with_predictions_no_ground_truth(db_session):
    """Test metrics calculation with predictions but no ground truth."""
    # Create a model
    model = MLModel(
        name="test_model",
        version="1.0.0",
        config={"file_path": "test.pkl", "threshold": 0.5},
        active=True
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    
    # Create predictions for yesterday
    target_date = date.today() - timedelta(days=1)
    base_time = datetime.combine(target_date, datetime.min.time())
    
    predictions = [
        Prediction(
            model_id=model.id,
            timestamp=base_time + timedelta(hours=i),
            probability=0.3 + i * 0.1,
            binary_prediction=True if i % 2 == 0 else False,
            threshold=0.5
        )
        for i in range(5)
    ]
    
    db_session.add_all(predictions)
    await db_session.commit()
    
    # Calculate metrics
    calculator = MetricsCalculator(db_session)
    result = await calculator.calculate_daily_metrics(model.id, target_date)
    
    # Should return None since ground truth is not implemented yet
    assert result is None


@pytest.mark.asyncio
async def test_calculate_daily_metrics_date_filtering(db_session):
    """Test that only predictions for the target date are considered."""
    # Create a model
    model = MLModel(
        name="test_model_filter",
        version="1.0.0",
        config={"file_path": "test.pkl"},
        active=True
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    
    # Create predictions for multiple days
    target_date = date.today() - timedelta(days=1)
    other_date = date.today() - timedelta(days=2)
    
    target_predictions = [
        Prediction(
            model_id=model.id,
            timestamp=datetime.combine(target_date, datetime.min.time()) + timedelta(hours=i),
            probability=0.5,
            binary_prediction=True,
            threshold=0.5
        )
        for i in range(3)
    ]
    
    other_predictions = [
        Prediction(
            model_id=model.id,
            timestamp=datetime.combine(other_date, datetime.min.time()) + timedelta(hours=i),
            probability=0.5,
            binary_prediction=True,
            threshold=0.5
        )
        for i in range(2)
    ]
    
    db_session.add_all(target_predictions + other_predictions)
    await db_session.commit()
    
    # Calculate metrics - should only consider target_date predictions
    calculator = MetricsCalculator(db_session)
    
    # We can't verify exact count without ground truth implementation,
    # but we can verify it doesn't crash and returns None (no ground truth)
    result = await calculator.calculate_daily_metrics(model.id, target_date)
    assert result is None


@pytest.mark.asyncio
async def test_fetch_ground_truth_not_implemented(db_session):
    """Test that _fetch_ground_truth returns None (not implemented yet)."""
    calculator = MetricsCalculator(db_session)
    
    target_date = date.today() - timedelta(days=1)
    result = await calculator._fetch_ground_truth(target_date, expected_count=10)
    
    assert result is None


@pytest.mark.asyncio
async def test_calculate_daily_metrics_with_mocked_ground_truth(db_session):
    """Test metrics calculation with mocked ground truth."""
    # Create a model
    model = MLModel(
        name="test_model_mocked",
        version="1.0.0",
        config={"file_path": "test.pkl"},
        active=True
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    
    # Create predictions
    target_date = date.today() - timedelta(days=1)
    base_time = datetime.combine(target_date, datetime.min.time())
    
    predictions = [
        Prediction(
            model_id=model.id,
            timestamp=base_time + timedelta(hours=i),
            probability=0.2 if i < 2 else 0.8,
            binary_prediction=False if i < 2 else True,
            threshold=0.5
        )
        for i in range(4)
    ]
    
    db_session.add_all(predictions)
    await db_session.commit()
    
    calculator = MetricsCalculator(db_session)
    
    # Mock ground truth: [0, 0, 1, 1] (perfect predictions)
    mock_ground_truth = [0, 0, 1, 1]
    
    with patch.object(calculator, '_fetch_ground_truth', return_value=mock_ground_truth):
        # This will still return None because the actual calculation is commented out
        # When ground truth is implemented, this test shows how it should work
        result = await calculator.calculate_daily_metrics(model.id, target_date)
        
        # Currently returns None (implementation pending)
        assert result is None
        
        # Future assertion when implemented:
        # assert result is not None
        # assert "f2_score" in result
        # assert result["f2_score"] == pytest.approx(1.0)  # Perfect predictions
