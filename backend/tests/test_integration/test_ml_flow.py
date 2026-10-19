"""Integration tests for the ML workflow.

Covers the end-to-end flow across the models, predictions, and metrics
endpoints, plus edge cases that are not covered by the unit-level API tests
in ``tests/test_api/``.
"""

from datetime import datetime, timedelta, date
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ml import MLModel, Prediction, ModelMetric


@pytest.fixture
async def sample_model(db_session: AsyncSession):
    """Create an active ML model in the database."""
    model = MLModel(
        name="test-baseline",
        version="v1.0",
        description="Test baseline model",
        config={"features": ["temperature", "humidity", "pressure"], "threshold": 0.5},
        active=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    return model


@pytest.fixture
async def sample_predictions(db_session: AsyncSession, sample_model: MLModel):
    """Create predictions for the sample model."""
    base_time = datetime.utcnow() - timedelta(days=1)
    predictions = []
    for i in range(5):
        pred = Prediction(
            model_id=sample_model.id,
            timestamp=base_time + timedelta(hours=i),
            probability=0.5 + (i * 0.1),
            threshold=0.5,
            binary_prediction=(0.5 + (i * 0.1)) >= 0.5,
        )
        db_session.add(pred)
        predictions.append(pred)
    await db_session.commit()
    return predictions


@pytest.fixture
async def sample_metrics(db_session: AsyncSession, sample_model: MLModel):
    """Create a metrics record for the sample model."""
    metric = ModelMetric(
        model_id=sample_model.id,
        date=datetime.utcnow().date(),
        brier_score=0.15,
        f1_score=0.82,
        f2_score=0.85,
        precision_score=0.80,
        recall=0.85,
        calibration_slope=0.95,
        threshold=0.5,
        confusion_matrix={"TP": 45, "FP": 10, "TN": 85, "FN": 8},
    )
    db_session.add(metric)
    await db_session.commit()
    await db_session.refresh(metric)
    return metric


class TestMLIntegrationFlow:
    """End-to-end tests for the ML workflow."""

    @pytest.mark.asyncio
    async def test_full_ml_workflow(
        self,
        client: AsyncClient,
        read_api_key: str,
        sample_model: MLModel,
        sample_predictions: list,
        sample_metrics: ModelMetric,
    ):
        """Complete flow: list models -> current predictions -> history -> metrics."""
        headers = {"X-API-Key": read_api_key}

        # List models
        response = await client.get("/models", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert len(data["models"]) > 0
        model = data["models"][0]
        assert model["name"] == "test-baseline"
        assert model["active"] is True
        model_id = model["id"]

        # Current predictions
        response = await client.get("/predictions/current", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "timestamp" in data
        assert "predictions" in data
        assert len(data["predictions"]) > 0

        # Prediction history
        start = (datetime.utcnow() - timedelta(days=2)).isoformat()
        end = datetime.utcnow().isoformat()
        response = await client.get(
            f"/predictions/history?model=test-baseline&start={start}&end={end}",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["model"] == "test-baseline"
        assert isinstance(data["data"], list)
        assert len(data["data"]) > 0

        # Latest metrics
        response = await client.get(f"/models/{model_id}/metrics", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["model"] == "test-baseline"
        assert "latest_metrics" in data
        metrics = data["latest_metrics"]
        assert "brier_score" in metrics
        assert "f1_score" in metrics
        assert "confusion_matrix" in metrics

        # Metrics history
        start_date = (datetime.utcnow() - timedelta(days=7)).date().isoformat()
        end_date = datetime.utcnow().date().isoformat()
        response = await client.get(
            f"/models/{model_id}/metrics/history?start={start_date}&end={end_date}",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["model"] == "test-baseline"
        assert "history" in data

    @pytest.mark.asyncio
    async def test_current_predictions_only_inactive_model(
        self, client: AsyncClient, read_api_key: str, db_session: AsyncSession
    ):
        """Predictions exist only for an inactive model -> current returns an empty list."""
        inactive = MLModel(
            name="test-inactive-only",
            version="v1.0",
            description="Inactive model",
            config={},
            active=False,
            created_at=datetime.utcnow(),
        )
        db_session.add(inactive)
        await db_session.commit()
        await db_session.refresh(inactive)

        db_session.add(
            Prediction(
                model_id=inactive.id,
                timestamp=datetime.utcnow(),
                probability=0.7,
                threshold=0.5,
                binary_prediction=True,
            )
        )
        await db_session.commit()

        response = await client.get(
            "/predictions/current", headers={"X-API-Key": read_api_key}
        )
        assert response.status_code == 200
        assert response.json()["predictions"] == []

    @pytest.mark.asyncio
    async def test_latest_metrics_when_no_metrics_today(
        self, client: AsyncClient, read_api_key: str, db_session: AsyncSession
    ):
        """Metrics exist only for past days -> endpoint returns the latest available."""
        model = MLModel(name="test-past-metrics", version="v1.0", active=True)
        db_session.add(model)
        await db_session.commit()
        await db_session.refresh(model)

        yesterday = datetime.utcnow().date() - timedelta(days=1)
        db_session.add(
            ModelMetric(
                model_id=model.id,
                date=yesterday,
                brier_score=0.20,
                f1_score=0.75,
                f2_score=0.78,
                precision_score=0.72,
                recall=0.80,
                calibration_slope=0.93,
                threshold=0.5,
                confusion_matrix={"TP": 40, "FP": 12, "TN": 80, "FN": 9},
            )
        )
        await db_session.commit()

        response = await client.get(
            f"/models/{model.id}/metrics", headers={"X-API-Key": read_api_key}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["model"] == "test-past-metrics"
        assert data["latest_metrics"]["brier_score"] == 0.20


class TestDailyTaskNoGroundTruth:
    """Integration tests for the daily ML task."""

    @pytest.mark.asyncio
    async def test_daily_task_no_ground_truth_stores_no_metrics(
        self, db_session: AsyncSession
    ):
        """The daily task generates predictions but stores no metrics without ground truth."""
        from app.ml.daily_task import DailyMLTask

        model = MLModel(
            name="test-daily-no-gt",
            version="v1.0",
            description="Daily task model",
            config={"threshold": 0.5},
            active=True,
        )
        db_session.add(model)
        await db_session.commit()
        await db_session.refresh(model)

        yesterday = date.today() - timedelta(days=1)
        base_time = datetime.combine(yesterday, datetime.min.time())
        for i in range(3):
            db_session.add(
                Prediction(
                    model_id=model.id,
                    timestamp=base_time + timedelta(hours=i),
                    probability=0.4 + i * 0.1,
                    threshold=0.5,
                    binary_prediction=False,
                )
            )
        await db_session.commit()

        task = DailyMLTask()
        features_df = pd.DataFrame(
            {"temperature": [20.0, 21.0, 22.0], "humidity": [60.0, 65.0, 70.0]}
        )

        # Real MetricsCalculator runs: ground truth is not implemented, so it returns None.
        with patch("app.ml.daily_task.PredictionService") as MockService:
            mock_service = MockService.return_value
            mock_service.predict_and_store = AsyncMock(return_value=[1, 2, 3])
            await task._process_model(db_session, model, features_df, yesterday)

        result = await db_session.execute(
            select(ModelMetric).where(ModelMetric.model_id == model.id)
        )
        assert result.scalars().all() == []
