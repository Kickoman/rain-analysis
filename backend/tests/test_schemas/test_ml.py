"""
Tests for ML schemas.
"""

import pytest
from datetime import datetime
from pydantic import ValidationError
from app.schemas.ml import (
    MLModelCreate,
    MLModelUpdate,
    MLModelResponse,
    MLModelListResponse,
    PredictionResponse,
    CurrentPredictionsResponse,
    PredictionHistoryItem,
    PredictionHistoryResponse,
    EvaluationDataPoint,
    EvaluationRequest,
    EvaluationPrediction,
    EvaluationResponse,
    ConfusionMatrix,
    ModelMetricsResponse,
    LatestMetricsResponse,
    MetricsHistoryResponse,
)


class TestMLModelSchemas:
    """Test ML model schemas."""
    
    def test_ml_model_create_valid(self):
        """Test valid MLModelCreate."""
        data = {
            "name": "test_model",
            "version": "1.0.0",
            "description": "Test model",
            "config": {"param": "value"},
            "active": True
        }
        model = MLModelCreate(**data)
        assert model.name == "test_model"
        assert model.version == "1.0.0"
        assert model.config == {"param": "value"}
    
    def test_ml_model_create_defaults(self):
        """Test MLModelCreate with defaults."""
        data = {"name": "test_model"}
        model = MLModelCreate(**data)
        assert model.name == "test_model"
        assert model.version is None
        assert model.config == {}
        assert model.active is True
    
    def test_ml_model_create_name_too_long(self):
        """Test MLModelCreate with name exceeding max_length."""
        data = {"name": "x" * 101}
        with pytest.raises(ValidationError) as exc_info:
            MLModelCreate(**data)
        assert "name" in str(exc_info.value)
    
    def test_ml_model_update_partial(self):
        """Test MLModelUpdate with partial data."""
        data = {"version": "2.0.0"}
        model = MLModelUpdate(**data)
        assert model.version == "2.0.0"
        assert model.description is None
    
    def test_ml_model_response_from_orm(self):
        """Test MLModelResponse with from_attributes."""
        # Simulate ORM object
        class MockModel:
            id = 1
            name = "test_model"
            version = "1.0.0"
            description = "Test"
            config = {"key": "value"}
            active = True
            created_at = datetime(2026, 1, 1, 12, 0, 0)
        
        response = MLModelResponse.model_validate(MockModel())
        assert response.id == 1
        assert response.name == "test_model"
    
    def test_ml_model_list_response(self):
        """Test MLModelListResponse."""
        models_data = [
            {
                "id": 1,
                "name": "model1",
                "version": "1.0",
                "description": None,
                "config": {},
                "active": True,
                "created_at": datetime.now()
            },
            {
                "id": 2,
                "name": "model2",
                "version": "2.0",
                "description": None,
                "config": {},
                "active": False,
                "created_at": datetime.now()
            }
        ]
        response = MLModelListResponse(models=models_data)
        assert len(response.models) == 2


class TestPredictionSchemas:
    """Test prediction schemas."""
    
    def test_prediction_response_valid(self):
        """Test valid PredictionResponse."""
        data = {
            "model": "test_model",
            "probability": 0.75,
            "binary_prediction": True,
            "threshold": 0.5
        }
        pred = PredictionResponse(**data)
        assert pred.probability == 0.75
        assert pred.binary_prediction is True
    
    def test_current_predictions_response(self):
        """Test CurrentPredictionsResponse."""
        data = {
            "timestamp": datetime.now(),
            "predictions": [
                {
                    "model": "model1",
                    "probability": 0.6,
                    "binary_prediction": True,
                    "threshold": 0.5
                },
                {
                    "model": "model2",
                    "probability": 0.3,
                    "binary_prediction": False,
                    "threshold": 0.5
                }
            ]
        }
        response = CurrentPredictionsResponse(**data)
        assert len(response.predictions) == 2
    
    def test_prediction_history_item(self):
        """Test PredictionHistoryItem."""
        data = {
            "timestamp": datetime.now(),
            "probability": 0.8,
            "binary_prediction": True
        }
        item = PredictionHistoryItem(**data)
        assert item.probability == 0.8
    
    def test_prediction_history_response(self):
        """Test PredictionHistoryResponse."""
        data = {
            "model": "test_model",
            "data": [
                {
                    "timestamp": datetime.now(),
                    "probability": 0.7,
                    "binary_prediction": True
                }
            ]
        }
        response = PredictionHistoryResponse(**data)
        assert response.model == "test_model"
        assert len(response.data) == 1


class TestEvaluationSchemas:
    """Test evaluation schemas."""
    
    def test_evaluation_data_point_minimal(self):
        """Test EvaluationDataPoint with required fields only."""
        data = {
            "timestamp": datetime.now(),
            "temperature": 20.5,
            "humidity": 65.0
        }
        point = EvaluationDataPoint(**data)
        assert point.temperature == 20.5
        assert point.pressure is None
    
    def test_evaluation_data_point_full(self):
        """Test EvaluationDataPoint with all fields."""
        data = {
            "timestamp": datetime.now(),
            "temperature": 20.5,
            "humidity": 65.0,
            "pressure": 1013.25,
            "wind_speed": 5.5
        }
        point = EvaluationDataPoint(**data)
        assert point.pressure == 1013.25
        assert point.wind_speed == 5.5
    
    def test_evaluation_request(self):
        """Test EvaluationRequest."""
        data = {
            "model": "test_model",
            "data": [
                {
                    "timestamp": datetime.now(),
                    "temperature": 20.0,
                    "humidity": 60.0
                }
            ]
        }
        request = EvaluationRequest(**data)
        assert request.model == "test_model"
        assert len(request.data) == 1
    
    def test_evaluation_prediction(self):
        """Test EvaluationPrediction."""
        data = {
            "timestamp": datetime.now(),
            "probability": 0.85
        }
        pred = EvaluationPrediction(**data)
        assert pred.probability == 0.85
    
    def test_evaluation_response(self):
        """Test EvaluationResponse."""
        data = {
            "predictions": [
                {
                    "timestamp": datetime.now(),
                    "probability": 0.6
                },
                {
                    "timestamp": datetime.now(),
                    "probability": 0.7
                }
            ]
        }
        response = EvaluationResponse(**data)
        assert len(response.predictions) == 2


class TestMetricsSchemas:
    """Test metrics schemas."""
    
    def test_confusion_matrix(self):
        """Test ConfusionMatrix."""
        data = {
            "TP": 10,
            "FP": 2,
            "FN": 1,
            "TN": 50
        }
        cm = ConfusionMatrix(**data)
        assert cm.TP == 10
        assert cm.TN == 50
    
    def test_model_metrics_response_minimal(self):
        """Test ModelMetricsResponse with minimal data."""
        data = {
            "date": datetime.now()
        }
        metrics = ModelMetricsResponse(**data)
        assert metrics.brier_score is None
        assert metrics.f1_score is None
    
    def test_model_metrics_response_full(self):
        """Test ModelMetricsResponse with all metrics."""
        data = {
            "date": datetime.now(),
            "brier_score": 0.15,
            "f1_score": 0.85,
            "f2_score": 0.82,
            "precision_score": 0.90,
            "recall": 0.80,
            "calibration_slope": 1.05,
            "threshold": 0.5,
            "confusion_matrix": {
                "TP": 10,
                "FP": 2,
                "FN": 1,
                "TN": 50
            }
        }
        metrics = ModelMetricsResponse(**data)
        assert metrics.brier_score == 0.15
        assert metrics.confusion_matrix.TP == 10
    
    def test_latest_metrics_response(self):
        """Test LatestMetricsResponse."""
        data = {
            "model": "test_model",
            "latest_metrics": {
                "date": datetime.now(),
                "f1_score": 0.85
            }
        }
        response = LatestMetricsResponse(**data)
        assert response.model == "test_model"
        assert response.latest_metrics.f1_score == 0.85
    
    def test_metrics_history_response(self):
        """Test MetricsHistoryResponse."""
        data = {
            "model": "test_model",
            "history": [
                {
                    "date": datetime.now(),
                    "f1_score": 0.85
                },
                {
                    "date": datetime.now(),
                    "f1_score": 0.87
                }
            ]
        }
        response = MetricsHistoryResponse(**data)
        assert response.model == "test_model"
        assert len(response.history) == 2


class TestSchemaValidation:
    """Test schema validation and constraints."""
    
    def test_version_max_length(self):
        """Test version field max_length constraint."""
        data = {
            "name": "test",
            "version": "x" * 21  # Exceeds max_length=20
        }
        with pytest.raises(ValidationError) as exc_info:
            MLModelCreate(**data)
        assert "version" in str(exc_info.value)
    
    def test_description_max_length(self):
        """Test description field max_length constraint."""
        data = {
            "name": "test",
            "description": "x" * 501  # Exceeds max_length=500
        }
        with pytest.raises(ValidationError) as exc_info:
            MLModelCreate(**data)
        assert "description" in str(exc_info.value)
    
    def test_nested_schema_validation(self):
        """Test nested schema validation (ConfusionMatrix in ModelMetricsResponse)."""
        data = {
            "date": datetime.now(),
            "confusion_matrix": {
                "TP": 10,
                "FP": 2,
                "FN": 1,
                "TN": 50
            }
        }
        metrics = ModelMetricsResponse(**data)
        assert isinstance(metrics.confusion_matrix, ConfusionMatrix)
        assert metrics.confusion_matrix.TP == 10
    
    def test_invalid_nested_schema(self):
        """Test invalid nested schema raises ValidationError."""
        data = {
            "date": datetime.now(),
            "confusion_matrix": {
                "TP": 10,
                # Missing required fields FP, FN, TN
            }
        }
        with pytest.raises(ValidationError):
            ModelMetricsResponse(**data)
