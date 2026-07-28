"""Tests for daily ML task."""
import pytest
from datetime import datetime, timedelta, date
from unittest.mock import AsyncMock, Mock, patch
import pandas as pd

from app.ml.daily_task import DailyMLTask
from app.models.ml import MLModel, Prediction, ModelMetric


@pytest.mark.asyncio
async def test_daily_task_no_weather_data(db_session):
    """Test that task exits gracefully when no weather data available."""
    task = DailyMLTask()
    
    # Mock _fetch_weather_data to return empty DataFrame
    with patch.object(task, '_fetch_weather_data', return_value=pd.DataFrame()):
        # Should not raise, just log warning and return
        await task.run()


@pytest.mark.asyncio
async def test_daily_task_no_active_models(db_session):
    """Test that task exits gracefully when no active models."""
    task = DailyMLTask()
    
    # Mock weather data available but no models
    mock_df = pd.DataFrame({'temp': [20, 21], 'humidity': [60, 65]})
    
    with patch.object(task, '_fetch_weather_data', return_value=mock_df):
        # No models in database, should exit gracefully
        await task.run()


@pytest.mark.asyncio
async def test_daily_task_process_model_success(db_session):
    """Test successful model processing."""
    # Create a test model
    model = MLModel(
        name="test_model",
        version="1.0.0",
        description="Test model",
        config={"file_path": "test.pkl", "threshold": 0.5},
        active=True
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    
    task = DailyMLTask()
    
    # Mock weather data
    mock_df = pd.DataFrame({
        'temperature': [20.0, 21.0, 19.0],
        'humidity': [60.0, 65.0, 58.0]
    })
    
    yesterday = date.today() - timedelta(days=1)
    
    # Mock PredictionService.predict_and_store
    mock_predictions = [
        Mock(id=1, probability=0.3, binary_prediction=0),
        Mock(id=2, probability=0.7, binary_prediction=1),
        Mock(id=3, probability=0.4, binary_prediction=0),
    ]
    
    with patch('app.ml.daily_task.PredictionService') as MockService:
        mock_service = MockService.return_value
        mock_service.predict_and_store = AsyncMock(return_value=mock_predictions)
        
        # Mock MetricsCalculator (returns None since no ground truth)
        with patch('app.ml.daily_task.MetricsCalculator') as MockCalculator:
            mock_calculator = MockCalculator.return_value
            mock_calculator.calculate_daily_metrics = AsyncMock(return_value=None)
            
            # Process the model
            await task._process_model(db_session, model, mock_df, yesterday)
            
            # Verify predict_and_store was called
            mock_service.predict_and_store.assert_called_once()


@pytest.mark.asyncio
async def test_daily_task_process_model_with_metrics(db_session):
    """Test model processing with metrics calculation."""
    # Create a test model
    model = MLModel(
        name="test_model_metrics",
        version="1.0.0",
        description="Test model with metrics",
        config={"file_path": "test.pkl", "threshold": 0.5},
        active=True
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    
    task = DailyMLTask()
    
    # Mock weather data
    mock_df = pd.DataFrame({
        'temperature': [20.0, 21.0],
        'humidity': [60.0, 65.0]
    })
    
    yesterday = date.today() - timedelta(days=1)
    
    # Mock predictions
    mock_predictions = [
        Mock(id=1, probability=0.3, binary_prediction=0),
        Mock(id=2, probability=0.7, binary_prediction=1),
    ]
    
    # Mock metrics (as if ground truth was available)
    mock_metrics = {
        "brier_score": 0.15,
        "f1_score": 0.85,
        "f2_score": 0.87,
        "precision": 0.9,
        "recall": 0.8,
        "threshold": 0.5,
        "confusion_matrix": {"TN": 45, "FP": 5, "FN": 10, "TP": 40}
    }
    
    with patch('app.ml.daily_task.PredictionService') as MockService:
        mock_service = MockService.return_value
        mock_service.predict_and_store = AsyncMock(return_value=mock_predictions)
        
        with patch('app.ml.daily_task.MetricsCalculator') as MockCalculator:
            mock_calculator = MockCalculator.return_value
            mock_calculator.calculate_daily_metrics = AsyncMock(return_value=mock_metrics)
            
            # Process the model
            await task._process_model(db_session, model, mock_df, yesterday)
            
            # Verify metrics were stored
            from sqlalchemy import select
            result = await db_session.execute(
                select(ModelMetric).where(ModelMetric.model_id == model.id)
            )
            metric = result.scalar_one_or_none()
            
            assert metric is not None
            assert metric.brier_score == 0.15
            assert metric.f2_score == 0.87


@pytest.mark.asyncio
async def test_daily_task_handles_model_error(db_session):
    """Test that task continues when one model fails."""
    # Create two test models
    model1 = MLModel(
        name="model1",
        version="1.0.0",
        config={"file_path": "test1.pkl"},
        active=True
    )
    model2 = MLModel(
        name="model2",
        version="1.0.0",
        config={"file_path": "test2.pkl"},
        active=True
    )
    db_session.add_all([model1, model2])
    await db_session.commit()
    
    task = DailyMLTask()
    
    # Mock weather data
    mock_df = pd.DataFrame({'temp': [20.0]})
    yesterday = date.today() - timedelta(days=1)
    
    with patch.object(task, '_fetch_weather_data', return_value=mock_df):
        with patch('app.ml.daily_task.PredictionService') as MockService:
            mock_service = MockService.return_value
            
            # First model fails, second succeeds
            mock_service.get_active_models = AsyncMock(return_value=[model1, model2])
            
            call_count = [0]
            async def side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise Exception("Model 1 failed")
                return [Mock(id=1, probability=0.5, binary_prediction=1)]
            
            mock_service.predict_and_store = AsyncMock(side_effect=side_effect)
            
            with patch('app.ml.daily_task.MetricsCalculator') as MockCalculator:
                mock_calculator = MockCalculator.return_value
                mock_calculator.calculate_daily_metrics = AsyncMock(return_value=None)
                
                # Should not raise, continues to model2
                await task.run()
                
                # Verify both models were attempted
                assert call_count[0] == 2


@pytest.mark.asyncio
async def test_fetch_weather_data_returns_empty(db_session):
    """Test _fetch_weather_data returns empty DataFrame (not yet implemented)."""
    task = DailyMLTask()
    yesterday = date.today() - timedelta(days=1)
    
    result = await task._fetch_weather_data(db_session, yesterday)
    
    assert isinstance(result, pd.DataFrame)
    assert result.empty


def test_run_daily_task_wrapper():
    """Test synchronous wrapper for scheduler."""
    from app.ml.daily_task import run_daily_task
    
    with patch('app.ml.daily_task.asyncio.run') as mock_run:
        run_daily_task()
        mock_run.assert_called_once()
