"""Tests for PredictionService."""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch
import pandas as pd
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.prediction_service import PredictionService


# Plain mock model classes for test data (not patched into the service;
# the service uses the real SQLAlchemy models for query construction).
class MLModel:
    """Mock MLModel for test fixtures."""
    def __init__(self):
        self.id = None
        self.name = None
        self.version = None
        self.description = None
        self.config = None
        self.active = None


class Prediction:
    """Mock Prediction for test fixtures."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        if not hasattr(self, 'id'):
            self.id = None
        if not hasattr(self, 'model_id'):
            self.model_id = None
        if not hasattr(self, 'timestamp'):
            self.timestamp = None
        if not hasattr(self, 'probability'):
            self.probability = None
        if not hasattr(self, 'threshold'):
            self.threshold = None
        if not hasattr(self, 'binary_prediction'):
            self.binary_prediction = None


@pytest.fixture
def mock_db_session():
    """Create mock async database session."""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.add = Mock()
    return session


@pytest.fixture
def mock_model_cache():
    """Create mock model cache."""
    cache = Mock()

    # Mock model with predict_proba
    mock_model = Mock()
    mock_model.predict_proba = Mock(return_value=np.array([[0.2, 0.8], [0.6, 0.4], [0.3, 0.7]]))

    cache.load_model = Mock(return_value=mock_model)
    return cache


@pytest.fixture
def prediction_service(mock_db_session, mock_model_cache):
    """Create PredictionService with mocked dependencies."""
    with patch('app.ml.model_loader.get_model_cache', return_value=mock_model_cache):
        service = PredictionService(mock_db_session)
        service.model_cache = mock_model_cache
        return service


@pytest.fixture
def sample_ml_model():
    """Create sample MLModel instance."""
    model = MLModel()
    model.id = 1
    model.name = "test_model"
    model.version = "1.0"
    model.description = "Test model"
    model.config = {"threshold": 0.6, "features": ["temp", "humidity"]}
    model.active = True
    return model


@pytest.fixture
def sample_features():
    """Create sample feature DataFrame."""
    return pd.DataFrame({
        "temp": [20.0, 22.5, 18.0],
        "humidity": [60.0, 75.0, 55.0]
    })


@pytest.fixture
def sample_timestamps():
    """Create sample timestamps."""
    return [
        datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 27, 11, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
    ]


def test_prediction_service_initialization(mock_db_session, mock_model_cache):
    """Test PredictionService initialization."""
    with patch('app.ml.model_loader.get_model_cache', return_value=mock_model_cache):
        service = PredictionService(mock_db_session)
        assert service.db == mock_db_session
        assert service.model_cache is not None


@pytest.mark.asyncio
async def test_get_active_models(prediction_service, mock_db_session, sample_ml_model):
    """Test retrieving active models."""
    # Mock database query result
    mock_result = Mock()
    mock_result.scalars = Mock(return_value=Mock(all=Mock(return_value=[sample_ml_model])))
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    models = await prediction_service.get_active_models()

    assert len(models) == 1
    assert models[0].name == "test_model"
    assert models[0].active is True


@pytest.mark.asyncio
async def test_get_model(prediction_service, mock_db_session, sample_ml_model):
    """Test retrieving model by ID."""
    mock_result = Mock()
    mock_result.scalar_one_or_none = Mock(return_value=sample_ml_model)
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    model = await prediction_service.get_model(1)

    assert model is not None
    assert model.id == 1
    assert model.name == "test_model"


@pytest.mark.asyncio
async def test_get_model_not_found(prediction_service, mock_db_session):
    """Test retrieving nonexistent model returns None."""
    mock_result = Mock()
    mock_result.scalar_one_or_none = Mock(return_value=None)
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    model = await prediction_service.get_model(999)

    assert model is None


def test_predict(prediction_service, mock_model_cache, sample_features):
    """Test generating predictions."""
    probabilities = prediction_service.predict("test_model", sample_features)

    assert len(probabilities) == 3
    assert all(isinstance(p, float) for p in probabilities)
    assert probabilities == [0.8, 0.4, 0.7]  # Positive class probabilities

    mock_model_cache.load_model.assert_called_once_with("test_model")


def test_predict_with_predict_method():
    """Test prediction with model that only has predict method."""
    mock_model = Mock()
    mock_model.predict = Mock(return_value=np.array([0.8, 0.4, 0.7]))
    del mock_model.predict_proba  # Ensure predict_proba doesn't exist

    mock_cache = Mock()
    mock_cache.load_model = Mock(return_value=mock_model)

    mock_db = AsyncMock()
    with patch('app.ml.model_loader.get_model_cache', return_value=mock_cache):
        service = PredictionService(mock_db)
        service.model_cache = mock_cache

        features = pd.DataFrame({"temp": [20, 22, 18]})
        probabilities = service.predict("test_model", features)

        assert probabilities == [0.8, 0.4, 0.7]


def test_predict_no_method_raises():
    """Test that model without predict methods raises AttributeError."""
    mock_model = Mock(spec=[])  # Empty spec = no methods

    mock_cache = Mock()
    mock_cache.load_model = Mock(return_value=mock_model)

    mock_db = AsyncMock()
    with patch('app.ml.model_loader.get_model_cache', return_value=mock_cache):
        service = PredictionService(mock_db)
        service.model_cache = mock_cache

        features = pd.DataFrame({"temp": [20, 22, 18]})

        with pytest.raises(AttributeError, match="has no predict_proba or predict method"):
            service.predict("test_model", features)


@pytest.mark.asyncio
async def test_predict_and_store(
    prediction_service,
    mock_db_session,
    sample_ml_model,
    sample_features,
    sample_timestamps
):
    """Test generating and storing predictions."""
    # Mock get_model to return the sample model
    mock_result = Mock()
    mock_result.scalar_one_or_none = Mock(return_value=sample_ml_model)
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    count = await prediction_service.predict_and_store(
        model_id=1,
        features=sample_features,
        timestamps=sample_timestamps
    )

    assert count == 3
    assert mock_db_session.add.call_count == 3
    mock_db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_predict_and_store_with_custom_threshold(
    prediction_service,
    mock_db_session,
    sample_ml_model,
    sample_features,
    sample_timestamps
):
    """Test storing predictions with custom threshold."""
    mock_result = Mock()
    mock_result.scalar_one_or_none = Mock(return_value=sample_ml_model)
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    await prediction_service.predict_and_store(
        model_id=1,
        features=sample_features,
        timestamps=sample_timestamps,
        threshold=0.75
    )

    # Check that stored predictions used custom threshold
    calls = mock_db_session.add.call_args_list
    assert len(calls) == 3

    for call in calls:
        prediction = call[0][0]
        assert prediction.threshold == 0.75
        assert prediction.model_id == 1


@pytest.mark.asyncio
async def test_predict_and_store_length_mismatch(
    prediction_service,
    sample_features,
    sample_timestamps
):
    """Test that length mismatch raises ValueError."""
    with pytest.raises(ValueError, match="length mismatch"):
        await prediction_service.predict_and_store(
            model_id=1,
            features=sample_features,
            timestamps=sample_timestamps[:-1]  # One fewer timestamp
        )


@pytest.mark.asyncio
async def test_predict_and_store_model_not_found(
    prediction_service,
    mock_db_session,
    sample_features,
    sample_timestamps
):
    """Test that nonexistent model raises ValueError."""
    mock_result = Mock()
    mock_result.scalar_one_or_none = Mock(return_value=None)
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="not found"):
        await prediction_service.predict_and_store(
            model_id=999,
            features=sample_features,
            timestamps=sample_timestamps
        )


@pytest.mark.asyncio
async def test_get_predictions(prediction_service, mock_db_session):
    """Test retrieving predictions."""
    # Mock predictions
    pred1 = Prediction(id=1, model_id=1, timestamp=datetime(2026, 7, 27, 10, 0), probability=0.8)
    pred2 = Prediction(id=2, model_id=1, timestamp=datetime(2026, 7, 27, 11, 0), probability=0.4)
    mock_predictions = [pred1, pred2]

    mock_result = Mock()
    mock_result.scalars = Mock(return_value=Mock(all=Mock(return_value=mock_predictions)))
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    predictions = await prediction_service.get_predictions(model_id=1, limit=100)

    assert len(predictions) == 2
    assert predictions[0].probability == 0.8


@pytest.mark.asyncio
async def test_get_predictions_with_time_range(prediction_service, mock_db_session):
    """Test retrieving predictions within time range."""
    mock_result = Mock()
    mock_result.scalars = Mock(return_value=Mock(all=Mock(return_value=[])))
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    start = datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)

    await prediction_service.get_predictions(
        model_id=1,
        start_time=start,
        end_time=end,
        limit=1000
    )

    # Verify query was executed
    mock_db_session.execute.assert_called_once()
