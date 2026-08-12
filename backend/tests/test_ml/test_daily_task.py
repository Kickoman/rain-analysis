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
        await task.run(db=db_session)


@pytest.mark.asyncio
async def test_daily_task_no_active_models(db_session):
    """Test that task exits gracefully when no active models."""
    task = DailyMLTask()
    
    # Mock weather data available but no models
    mock_df = pd.DataFrame({'temp': [20, 21], 'humidity': [60, 65]})
    
    with patch.object(task, '_fetch_weather_data', return_value=mock_df):
        # No models in database, should exit gracefully
        # Pass db_session to avoid creating new session that would fail
        await task.run(db=db_session)


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
            
            # Verify metrics calculation was attempted
            mock_calculator.calculate_daily_metrics.assert_called_once_with(
                model.id, yesterday
            )


@pytest.mark.asyncio
async def test_daily_task_model_error_continues(db_session):
    """Test that error in one model doesn't stop processing others."""
    # Create two test models
    model1 = MLModel(
        name="test_model_1",
        version="1.0.0",
        description="Test model 1",
        config={"file_path": "test1.pkl", "threshold": 0.5},
        active=True
    )
    model2 = MLModel(
        name="test_model_2",
        version="1.0.0",
        description="Test model 2",
        config={"file_path": "test2.pkl", "threshold": 0.5},
        active=True
    )
    db_session.add_all([model1, model2])
    await db_session.commit()
    
    task = DailyMLTask()
    
    mock_df = pd.DataFrame({'temp': [20, 21], 'humidity': [60, 65]})
    
    # Mock first model to raise error, second to succeed
    with patch.object(task, '_fetch_weather_data', return_value=mock_df):
        with patch('app.ml.daily_task.PredictionService') as MockService:
            mock_service = MockService.return_value
            mock_service.get_active_models = AsyncMock(return_value=[model1, model2])
            
            # First call raises, second succeeds
            mock_service.predict_and_store = AsyncMock(
                side_effect=[Exception("Model 1 failed"), [Mock()]]
            )
            
            with patch('app.ml.daily_task.MetricsCalculator') as MockCalculator:
                mock_calculator = MockCalculator.return_value
                mock_calculator.calculate_daily_metrics = AsyncMock(return_value=None)
                
                # Should not raise, just log error for model1 and continue to model2
                await task.run(db=db_session)
                
                # Verify both models were attempted
                assert mock_service.predict_and_store.call_count == 2


@pytest.mark.asyncio
async def test_daily_task_metrics_storage(db_session):
    """Test that metrics are stored when available."""
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
    mock_df = pd.DataFrame({'temp': [20, 21], 'humidity': [60, 65]})
    yesterday = date.today() - timedelta(days=1)
    
    mock_predictions = [Mock(id=1, probability=0.7, binary_prediction=1)]
    mock_metrics = {
        'brier_score': 0.25,
        'f1_score': 0.85,
        'f2_score': 0.88,
        'precision': 0.80,
        'recall': 0.90,
        'threshold': 0.5,
        'confusion_matrix': {'TP': 10, 'TN': 8, 'FP': 2, 'FN': 1}
    }
    
    with patch('app.ml.daily_task.PredictionService') as MockService:
        mock_service = MockService.return_value
        mock_service.predict_and_store = AsyncMock(return_value=mock_predictions)
        
        with patch('app.ml.daily_task.MetricsCalculator') as MockCalculator:
            mock_calculator = MockCalculator.return_value
            mock_calculator.calculate_daily_metrics = AsyncMock(return_value=mock_metrics)
            
            await task._process_model(db_session, model, mock_df, yesterday)
            
            # Verify metric was stored in database
            result = await db_session.execute(
                f"SELECT * FROM model_metrics WHERE model_id = {model.id}"
            )
            metrics_records = result.fetchall()
            assert len(metrics_records) == 1
            assert metrics_records[0][2] == yesterday  # date column
