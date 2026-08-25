"""Tests for predictions API endpoints."""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import select

from app.models.ml import MLModel, Prediction
from app.models.api_key import APIKey
from app.auth.crypto import generate_api_key


@pytest.fixture
async def test_model(db_session):
    """Create a test ML model."""
    model = MLModel(
        name="test_model",
        version="1.0",
        description="Test model for predictions",
        config={"threshold": 0.5},
        active=True
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    return model


@pytest.fixture
async def inactive_model(db_session):
    """Create an inactive test ML model."""
    model = MLModel(
        name="inactive_model",
        version="1.0",
        description="Inactive test model",
        config={"threshold": 0.5},
        active=False
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    return model


@pytest.fixture
async def test_predictions(db_session, test_model):
    """Create test predictions."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    predictions = []
    
    for i in range(5):
        pred = Prediction(
            model_id=test_model.id,
            timestamp=base_time + timedelta(hours=i),
            probability=0.3 + (i * 0.1),
            threshold=0.5,
            binary_prediction=(0.3 + i * 0.1) >= 0.5
        )
        db_session.add(pred)
        predictions.append(pred)
    
    await db_session.commit()
    return predictions


@pytest.fixture
async def read_api_key(db_session):
    """Create a read-scope API key."""
    full_key, key_hash, key_prefix = generate_api_key("test")
    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="test_user",
        description="Test read key",
        scope="read",
        rate_limit_rpm=100,
        rate_limit_rph=1000,
        rate_limit_rpd=10000,
        is_active=True
    )
    db_session.add(api_key)
    await db_session.commit()
    await db_session.refresh(api_key)
    api_key.full_key = full_key  # Store for testing
    return api_key


@pytest.fixture
async def write_api_key(db_session):
    """Create a write-scope API key."""
    full_key, key_hash, key_prefix = generate_api_key("test")
    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="test_user",
        description="Test write key",
        scope="write",
        rate_limit_rpm=100,
        rate_limit_rph=1000,
        rate_limit_rpd=10000,
        is_active=True
    )
    db_session.add(api_key)
    await db_session.commit()
    await db_session.refresh(api_key)
    api_key.full_key = full_key  # Store for testing
    return api_key


class TestGetCurrentPredictions:
    """Tests for GET /predictions/current endpoint."""
    
    async def test_get_current_predictions_success(
        self, client, read_api_key, test_predictions
    ):
        """Test getting current predictions successfully."""
        response = await client.get(
            "/api/v1/predictions/current",
            headers={"X-API-Key": read_api_key.full_key}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "timestamp" in data
        assert "predictions" in data
        assert len(data["predictions"]) == 1  # One active model
        
        pred = data["predictions"][0]
        assert pred["model"] == "test_model"
        assert "probability" in pred
        assert "binary_prediction" in pred
        assert "threshold" in pred
    
    async def test_get_current_predictions_no_data(
        self, client, read_api_key, test_model
    ):
        """Test getting current predictions when no predictions exist."""
        response = await client.get(
            "/api/v1/predictions/current",
            headers={"X-API-Key": read_api_key.full_key}
        )
        
        assert response.status_code == 404
        assert "No predictions found" in response.json()["detail"]
    
    async def test_get_current_predictions_excludes_inactive_models(
        self, client, read_api_key, db_session, test_predictions, inactive_model
    ):
        """Test that current predictions excludes inactive models."""
        # Add prediction for inactive model at the same latest timestamp
        latest_timestamp = test_predictions[-1].timestamp
        pred = Prediction(
            model_id=inactive_model.id,
            timestamp=latest_timestamp,
            probability=0.8,
            threshold=0.5,
            binary_prediction=True
        )
        db_session.add(pred)
        await db_session.commit()
        
        response = await client.get(
            "/api/v1/predictions/current",
            headers={"X-API-Key": read_api_key.full_key}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should only have prediction from active model
        assert len(data["predictions"]) == 1
        assert data["predictions"][0]["model"] == "test_model"
    
    async def test_get_current_predictions_no_auth(self, client):
        """Test getting current predictions without authentication."""
        response = await client.get("/api/v1/predictions/current")
        
        assert response.status_code == 401


class TestGetPredictionHistory:
    """Tests for GET /predictions/history endpoint."""
    
    async def test_get_prediction_history_success(
        self, client, read_api_key, test_predictions
    ):
        """Test getting prediction history successfully."""
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        end_time = datetime(2024, 1, 1, 16, 0, 0)
        
        response = await client.get(
            "/api/v1/predictions/history",
            params={
                "model": "test_model",
                "start": start_time.isoformat(),
                "end": end_time.isoformat()
            },
            headers={"X-API-Key": read_api_key.full_key}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["model"] == "test_model"
        assert "data" in data
        assert len(data["data"]) == 5  # All 5 predictions in range
        
        # Check data is sorted by timestamp
        timestamps = [item["timestamp"] for item in data["data"]]
        assert timestamps == sorted(timestamps)
    
    async def test_get_prediction_history_partial_range(
        self, client, read_api_key, test_predictions
    ):
        """Test getting prediction history with partial date range."""
        start_time = datetime(2024, 1, 1, 13, 0, 0)
        end_time = datetime(2024, 1, 1, 15, 0, 0)
        
        response = await client.get(
            "/api/v1/predictions/history",
            params={
                "model": "test_model",
                "start": start_time.isoformat(),
                "end": end_time.isoformat()
            },
            headers={"X-API-Key": read_api_key.full_key}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["data"]) == 3  # Only 3 predictions in this range
    
    async def test_get_prediction_history_model_not_found(
        self, client, read_api_key
    ):
        """Test getting prediction history for non-existent model."""
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        end_time = datetime(2024, 1, 1, 16, 0, 0)
        
        response = await client.get(
            "/api/v1/predictions/history",
            params={
                "model": "nonexistent_model",
                "start": start_time.isoformat(),
                "end": end_time.isoformat()
            },
            headers={"X-API-Key": read_api_key.full_key}
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
    
    async def test_get_prediction_history_no_auth(self, client):
        """Test getting prediction history without authentication."""
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        end_time = datetime(2024, 1, 1, 16, 0, 0)
        
        response = await client.get(
            "/api/v1/predictions/history",
            params={
                "model": "test_model",
                "start": start_time.isoformat(),
                "end": end_time.isoformat()
            }
        )
        
        assert response.status_code == 401


class TestEvaluateModel:
    """Tests for POST /predictions/evaluate endpoint."""
    
    async def test_evaluate_model_success(
        self, client, write_api_key, test_model, monkeypatch
    ):
        """Test evaluating model successfully."""
        # Mock the prediction service to avoid needing actual model files
        def mock_predict(self, model_name, features_df):
            return [0.6, 0.7, 0.8]
        
        from app.ml import prediction_service
        monkeypatch.setattr(
            prediction_service.PredictionService,
            "predict",
            mock_predict
        )
        
        request_data = {
            "model": "test_model",
            "data": [
                {
                    "timestamp": "2024-01-01T12:00:00",
                    "temperature": 20.0,
                    "humidity": 60.0,
                    "pressure": 1013.0,
                    "wind_speed": 5.0
                },
                {
                    "timestamp": "2024-01-01T13:00:00",
                    "temperature": 21.0,
                    "humidity": 65.0,
                    "pressure": 1012.0,
                    "wind_speed": 6.0
                },
                {
                    "timestamp": "2024-01-01T14:00:00",
                    "temperature": 22.0,
                    "humidity": 70.0,
                    "pressure": 1011.0,
                    "wind_speed": 7.0
                }
            ]
        }
        
        response = await client.post(
            "/api/v1/predictions/evaluate",
            json=request_data,
            headers={"X-API-Key": write_api_key.full_key}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "predictions" in data
        assert len(data["predictions"]) == 3
        
        for pred in data["predictions"]:
            assert "timestamp" in pred
            assert "probability" in pred
            assert 0 <= pred["probability"] <= 1
    
    async def test_evaluate_model_not_found(
        self, client, write_api_key
    ):
        """Test evaluating non-existent model."""
        request_data = {
            "model": "nonexistent_model",
            "data": [
                {
                    "timestamp": "2024-01-01T12:00:00",
                    "temperature": 20.0,
                    "humidity": 60.0
                }
            ]
        }
        
        response = await client.post(
            "/api/v1/predictions/evaluate",
            json=request_data,
            headers={"X-API-Key": write_api_key.full_key}
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
    
    async def test_evaluate_model_empty_data(
        self, client, write_api_key, test_model
    ):
        """Test evaluating model with empty data."""
        request_data = {
            "model": "test_model",
            "data": []
        }
        
        response = await client.post(
            "/api/v1/predictions/evaluate",
            json=request_data,
            headers={"X-API-Key": write_api_key.full_key}
        )
        
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()
    
    async def test_evaluate_model_requires_write_scope(
        self, client, read_api_key, test_model
    ):
        """Test that evaluation requires write scope."""
        request_data = {
            "model": "test_model",
            "data": [
                {
                    "timestamp": "2024-01-01T12:00:00",
                    "temperature": 20.0,
                    "humidity": 60.0
                }
            ]
        }
        
        response = await client.post(
            "/api/v1/predictions/evaluate",
            json=request_data,
            headers={"X-API-Key": read_api_key.full_key}
        )
        
        assert response.status_code == 403
        assert "Insufficient permissions" in response.json()["detail"]
    
    async def test_evaluate_model_no_auth(self, client):
        """Test evaluating model without authentication."""
        request_data = {
            "model": "test_model",
            "data": [
                {
                    "timestamp": "2024-01-01T12:00:00",
                    "temperature": 20.0,
                    "humidity": 60.0
                }
            ]
        }
        
        response = await client.post(
            "/api/v1/predictions/evaluate",
            json=request_data
        )
        
        assert response.status_code == 401
