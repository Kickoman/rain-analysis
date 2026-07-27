"""Tests for models API endpoints."""

import pytest
from datetime import datetime, date, timedelta
from fastapi import status
from sqlalchemy import select

from app.models.ml import MLModel, ModelMetric

@pytest.fixture
async def auth_headers(db_session):
    """Create authentication headers with a valid API key."""
    from app.models.api_key import APIKey
    from app.auth.crypto import generate_api_key
    
    full_key, key_hash, key_prefix = generate_api_key("test")
    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="test_user",
        description="Test API key",
        scope="read",
        rate_limit_rpm=100,
        rate_limit_rph=1000,
        rate_limit_rpd=10000,
        is_active=True
    )
    db_session.add(api_key)
    await db_session.commit()
    
    return {"X-API-Key": full_key}



@pytest.mark.asyncio
class TestListModels:
    """Tests for GET /models endpoint."""
    
    async def test_list_models_active_only(self, client, auth_headers, db_session):
        """Test listing only active models (default behavior)."""
        # Create test models
        active_model = MLModel(
            name="active_model",
            version="1.0",
            description="Active test model",
            active=True
        )
        inactive_model = MLModel(
            name="inactive_model",
            version="1.0",
            description="Inactive test model",
            active=False
        )
        db_session.add_all([active_model, inactive_model])
        await db_session.commit()
        
        # Test default behavior (active_only=True)
        response = await client.get("/models", headers=auth_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "models" in data
        assert len(data["models"]) == 1
        assert data["models"][0]["name"] == "active_model"
        assert data["models"][0]["active"] is True
    
    async def test_list_models_all(self, client, auth_headers, db_session):
        """Test listing all models including inactive ones."""
        # Create test models
        active_model = MLModel(
            name="active_model",
            version="1.0",
            description="Active test model",
            active=True
        )
        inactive_model = MLModel(
            name="inactive_model",
            version="1.0",
            description="Inactive test model",
            active=False
        )
        db_session.add_all([active_model, inactive_model])
        await db_session.commit()
        
        # Test with active_only=False
        response = await client.get("/models?active_only=false", headers=auth_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "models" in data
        assert len(data["models"]) == 2
        
        # Check both models are present
        model_names = [m["name"] for m in data["models"]]
        assert "active_model" in model_names
        assert "inactive_model" in model_names
    
    async def test_list_models_empty(self, client, auth_headers, db_session):
        """Test listing models when database is empty."""
        response = await client.get("/models", headers=auth_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "models" in data
        assert len(data["models"]) == 0
    
    async def test_list_models_sorted_by_name(self, client, auth_headers, db_session):
        """Test that models are returned sorted by name."""
        # Create models in non-alphabetical order
        model_c = MLModel(name="charlie", version="1.0", active=True)
        model_a = MLModel(name="alpha", version="1.0", active=True)
        model_b = MLModel(name="bravo", version="1.0", active=True)
        
        db_session.add_all([model_c, model_a, model_b])
        await db_session.commit()
        
        response = await client.get("/models", headers=auth_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        model_names = [m["name"] for m in data["models"]]
        assert model_names == ["alpha", "bravo", "charlie"]
    
    async def test_list_models_no_auth(self, client):
        """Test that listing models requires authentication."""
        response = await client.get("/models")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    async def test_list_models_invalid_api_key(self, client):
        """Test that listing models rejects invalid API key."""
        response = await client.get("/models", headers={"X-API-Key": "invalid_key"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
class TestGetModel:
    """Tests for GET /models/{model_id} endpoint."""
    
    async def test_get_model_success(self, client, auth_headers, db_session):
        """Test retrieving a specific model by ID."""
        model = MLModel(
            name="test_model",
            version="1.0.0",
            description="A test model",
            config={"param1": "value1", "param2": 42},
            active=True
        )
        db_session.add(model)
        await db_session.commit()
        await db_session.refresh(model)
        
        response = await client.get(f"/models/{model.id}", headers=auth_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == model.id
        assert data["name"] == "test_model"
        assert data["version"] == "1.0.0"
        assert data["description"] == "A test model"
        assert data["config"] == {"param1": "value1", "param2": 42}
        assert data["active"] is True
        assert "created_at" in data
    
    async def test_get_model_not_found(self, client, auth_headers):
        """Test retrieving a non-existent model."""
        response = await client.get("/models/99999", headers=auth_headers)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in response.json()["detail"].lower()
    
    async def test_get_model_no_auth(self, client, db_session):
        """Test that getting a model requires authentication."""
        model = MLModel(name="test_model", active=True)
        db_session.add(model)
        await db_session.commit()
        await db_session.refresh(model)
        
        response = await client.get(f"/models/{model.id}")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
class TestGetLatestMetrics:
    """Tests for GET /models/{model_id}/metrics endpoint."""
    
    async def test_get_latest_metrics_success(self, client, auth_headers, db_session):
        """Test retrieving latest metrics for a model."""
        # Create model
        model = MLModel(name="test_model", active=True)
        db_session.add(model)
        await db_session.commit()
        await db_session.refresh(model)
        
        # Create metrics (older and newer)
        older_metric = ModelMetric(
            model_id=model.id,
            date=datetime.now() - timedelta(days=2),
            brier_score=0.15,
            f1_score=0.75,
            f2_score=0.78,
            precision_score=0.72,
            recall=0.80,
            calibration_slope=0.95,
            threshold=0.5,
            confusion_matrix={"TP": 80, "FP": 20, "FN": 15, "TN": 85}
        )
        latest_metric = ModelMetric(
            model_id=model.id,
            date=datetime.now(),
            brier_score=0.12,
            f1_score=0.82,
            f2_score=0.85,
            precision_score=0.80,
            recall=0.85,
            calibration_slope=0.98,
            threshold=0.5,
            confusion_matrix={"TP": 85, "FP": 15, "FN": 10, "TN": 90}
        )
        db_session.add_all([older_metric, latest_metric])
        await db_session.commit()
        
        response = await client.get(f"/models/{model.id}/metrics", headers=auth_headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["model"] == "test_model"
        assert "latest_metrics" in data
        
        metrics = data["latest_metrics"]
        assert metrics["brier_score"] == 0.12
        assert metrics["f1_score"] == 0.82
        assert metrics["f2_score"] == 0.85
        assert metrics["precision_score"] == 0.80
        assert metrics["recall"] == 0.85
        assert metrics["calibration_slope"] == 0.98
        assert metrics["threshold"] == 0.5
        assert metrics["confusion_matrix"] == {"TP": 85, "FP": 15, "FN": 10, "TN": 90}
    
    async def test_get_latest_metrics_model_not_found(self, client, auth_headers):
        """Test getting metrics for non-existent model."""
        response = await client.get("/models/99999/metrics", headers=auth_headers)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "model" in response.json()["detail"].lower()
        assert "not found" in response.json()["detail"].lower()
    
    async def test_get_latest_metrics_no_metrics(self, client, auth_headers, db_session):
        """Test getting metrics for a model with no metrics."""
        model = MLModel(name="test_model", active=True)
        db_session.add(model)
        await db_session.commit()
        await db_session.refresh(model)
        
        response = await client.get(f"/models/{model.id}/metrics", headers=auth_headers)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "no metrics" in response.json()["detail"].lower()
    
    async def test_get_latest_metrics_no_auth(self, client, db_session):
        """Test that getting metrics requires authentication."""
        model = MLModel(name="test_model", active=True)
        db_session.add(model)
        await db_session.commit()
        await db_session.refresh(model)
        
        response = await client.get(f"/models/{model.id}/metrics")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
class TestGetMetricsHistory:
    """Tests for GET /models/{model_id}/metrics/history endpoint."""
    
    async def test_get_metrics_history_success(self, client, auth_headers, db_session):
        """Test retrieving metrics history for a date range."""
        # Create model
        model = MLModel(name="test_model", active=True)
        db_session.add(model)
        await db_session.commit()
        await db_session.refresh(model)
        
        # Create metrics for different dates
        base_date = date.today()
        metrics = []
        for i in range(5):
            metric = ModelMetric(
                model_id=model.id,
                date=base_date - timedelta(days=i),
                brier_score=0.10 + i * 0.01,
                f1_score=0.85 - i * 0.01,
                f2_score=0.87 - i * 0.01,
                precision_score=0.83 - i * 0.01,
                recall=0.88 - i * 0.01,
                calibration_slope=0.97 - i * 0.01,
                threshold=0.5,
                confusion_matrix={"TP": 90 - i, "FP": 10 + i, "FN": 8 + i, "TN": 92 - i}
            )
            metrics.append(metric)
        
        db_session.add_all(metrics)
        await db_session.commit()
        
        # Query for a subset of the date range
        start_date = base_date - timedelta(days=3)
        end_date = base_date
        
        response = await client.get(
            f"/models/{model.id}/metrics/history?start={start_date}&end={end_date}",
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["model"] == "test_model"
        assert "history" in data
        assert len(data["history"]) == 4  # 4 days inclusive
        
        # Verify metrics are ordered by date ascending
        dates = [item["date"] for item in data["history"]]
        assert dates == sorted(dates)
    
    async def test_get_metrics_history_empty_range(self, client, auth_headers, db_session):
        """Test retrieving metrics history with no data in range."""
        model = MLModel(name="test_model", active=True)
        db_session.add(model)
        await db_session.commit()
        await db_session.refresh(model)
        
        # Create metric outside the query range
        old_metric = ModelMetric(
            model_id=model.id,
            date=date.today() - timedelta(days=100),
            brier_score=0.15
        )
        db_session.add(old_metric)
        await db_session.commit()
        
        # Query recent range with no data
        start_date = date.today() - timedelta(days=7)
        end_date = date.today()
        
        response = await client.get(
            f"/models/{model.id}/metrics/history?start={start_date}&end={end_date}",
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["model"] == "test_model"
        assert len(data["history"]) == 0
    
    async def test_get_metrics_history_model_not_found(self, client, auth_headers):
        """Test getting history for non-existent model."""
        start_date = date.today() - timedelta(days=7)
        end_date = date.today()
        
        response = await client.get(
            f"/models/99999/metrics/history?start={start_date}&end={end_date}",
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "model" in response.json()["detail"].lower()
        assert "not found" in response.json()["detail"].lower()
    
    async def test_get_metrics_history_invalid_date_range(self, client, auth_headers, db_session):
        """Test that start date must be before end date."""
        model = MLModel(name="test_model", active=True)
        db_session.add(model)
        await db_session.commit()
        await db_session.refresh(model)
        
        # Start date after end date
        start_date = date.today()
        end_date = date.today() - timedelta(days=7)
        
        response = await client.get(
            f"/models/{model.id}/metrics/history?start={start_date}&end={end_date}",
            headers=auth_headers
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "start date" in response.json()["detail"].lower()
    
    async def test_get_metrics_history_missing_params(self, client, auth_headers, db_session):
        """Test that start and end parameters are required."""
        model = MLModel(name="test_model", active=True)
        db_session.add(model)
        await db_session.commit()
        await db_session.refresh(model)
        
        # Missing both parameters
        response = await client.get(f"/models/{model.id}/metrics/history", headers=auth_headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        
        # Missing end parameter
        start_date = date.today() - timedelta(days=7)
        response = await client.get(
            f"/models/{model.id}/metrics/history?start={start_date}",
            headers=auth_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        
        # Missing start parameter
        end_date = date.today()
        response = await client.get(
            f"/models/{model.id}/metrics/history?end={end_date}",
            headers=auth_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    async def test_get_metrics_history_no_auth(self, client, db_session):
        """Test that getting metrics history requires authentication."""
        model = MLModel(name="test_model", active=True)
        db_session.add(model)
        await db_session.commit()
        await db_session.refresh(model)
        
        start_date = date.today() - timedelta(days=7)
        end_date = date.today()
        
        response = await client.get(
            f"/models/{model.id}/metrics/history?start={start_date}&end={end_date}"
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
class TestModelsIntegration:
    """Integration tests for models API."""
    
    async def test_full_workflow(self, client, auth_headers, db_session):
        """Test complete workflow: create models, add metrics, query all endpoints."""
        # Create multiple models
        model1 = MLModel(name="model_a", version="1.0", active=True)
        model2 = MLModel(name="model_b", version="2.0", active=True)
        model3 = MLModel(name="model_c", version="1.5", active=False)
        
        db_session.add_all([model1, model2, model3])
        await db_session.commit()
        await db_session.refresh(model1)
        await db_session.refresh(model2)
        
        # Add metrics to model1
        for i in range(3):
            metric = ModelMetric(
                model_id=model1.id,
                date=date.today() - timedelta(days=i),
                brier_score=0.10 + i * 0.01,
                f1_score=0.85 - i * 0.01
            )
            db_session.add(metric)
        
        await db_session.commit()
        
        # Test 1: List active models
        response = await client.get("/models", headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["models"]) == 2
        
        # Test 2: Get specific model
        response = await client.get(f"/models/{model1.id}", headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "model_a"
        
        # Test 3: Get latest metrics
        response = await client.get(f"/models/{model1.id}/metrics", headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["model"] == "model_a"
        assert response.json()["latest_metrics"]["brier_score"] == 0.10
        
        # Test 4: Get metrics history
        start_date = date.today() - timedelta(days=2)
        end_date = date.today()
        response = await client.get(
            f"/models/{model1.id}/metrics/history?start={start_date}&end={end_date}",
            headers=auth_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["history"]) == 3
        
        # Test 5: Model without metrics returns 404
        response = await client.get(f"/models/{model2.id}/metrics", headers=auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND
