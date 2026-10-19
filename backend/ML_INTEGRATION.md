# ML Integration Guide

## Overview

The ML integration provides a complete system for serving machine learning predictions through a REST API. Models are trained offline, registered in the database, and used for daily predictions via a background task.

## Architecture

```
┌─────────────────────────────────────────────┐
│  Daily Background Task (00:00 UTC)          │
│  - Fetch weather data                       │
│  - Load active models                       │
│  - Generate predictions                     │
│  - Calculate metrics                        │
└─────────────────────────────────────────────┘
         ↓                          ↓
┌──────────────────┐      ┌──────────────────┐
│  Predictions     │      │  Model Metrics   │
│  Database        │      │  Database        │
└──────────────────┘      └──────────────────┘
         ↑                          ↑
┌─────────────────────────────────────────────┐
│  REST API                                   │
│  - /predictions/current                     │
│  - /predictions/history                     │
│  - /predictions/evaluate                    │
│  - /models                                  │
│  - /models/{id}/metrics                     │
└─────────────────────────────────────────────┘
```

## Components

### 1. Model Registration

Models must be registered in the database before use. Each model requires:

- **name**: Unique identifier (e.g., "baseline", "ensemble")
- **version**: Version string (e.g., "v1.0")
- **description**: Human-readable description
- **config**: JSON configuration including:
  - `features`: List of required feature columns
  - `threshold`: Binary classification threshold (default: 0.5)
  - `file_path`: Path to pickled model file (relative to models directory)
- **active**: Boolean flag for production use

#### Database Registration

```python
from app.models.ml import MLModel
from app.database import AsyncSessionLocal

async def register_model():
    async with AsyncSessionLocal() as session:
        model = MLModel(
            name="baseline",
            version="v1.0",
            description="Temperature + humidity baseline model",
            config={
                "features": ["temperature", "humidity", "pressure"],
                "threshold": 0.5,
                "file_path": "models/baseline.pkl"
            },
            active=True
        )
        session.add(model)
        await session.commit()
```

### 2. Model Files

Models must be scikit-learn compatible objects saved using pickle:

```python
import pickle
from sklearn.ensemble import RandomForestClassifier

# Train model
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)

# Save to file
with open("models/baseline.pkl", "wb") as f:
    pickle.dump(model, f)
```

**Requirements:**
- Model must implement `predict_proba(X)` method
- Returns array of shape `(n_samples, 2)` with `[prob_class_0, prob_class_1]`
- Features must match the order specified in model config

### 3. PredictionService

Core service for generating predictions:

```python
from app.ml.prediction_service import PredictionService
import pandas as pd

service = PredictionService(db_session)

# Prepare feature data
features = pd.DataFrame({
    "temperature": [15.5, 16.0],
    "humidity": [80.0, 75.0],
    "pressure": [1013.25, 1012.80]
})

# Generate predictions
probabilities = service.predict("baseline", features)
# Returns: array([0.65, 0.42])
```

### 4. Model Caching

The `ModelCache` singleton caches loaded models in memory:

```python
from app.ml.model_loader import get_model_cache

cache = get_model_cache()

# First load: reads from disk and deserializes the pickle
model = cache.load_model("baseline", Path("models/baseline.pkl"))

# Subsequent loads: returns the cached object without disk I/O
model = cache.load_model("baseline", Path("models/baseline.pkl"))

# Clear cache when model is updated
cache.clear_cache("baseline")
```

**Performance:**
- First load: disk I/O + pickle deserialization
- Cached load: in-memory lookup, no disk access
- Speedup: ~20-50x for repeated loads (measured on the `test_cache_hit_performance`-style benchmark)

### 5. Background Task

Automated daily predictions at 00:00 UTC using APScheduler:

```python
# Configured in app/main.py
scheduler.add_job(
    daily_ml_task,
    trigger="cron",
    hour=0,
    minute=0,
    timezone="UTC",
    id="daily_ml_task"
)
```

**Task workflow:**
1. Fetch weather data for previous day
2. Load all active models
3. Generate predictions for each model
4. Save predictions to database
5. Calculate performance metrics (if ground truth available)
6. Log results

**Manual trigger** (admin only):
```bash
curl -X POST \
  -H "X-API-Key: $ADMIN_KEY" \
  http://localhost:8000/admin/ml/trigger-daily-task
```

### 6. Metrics Calculation

Performance metrics are calculated daily when ground truth data is available:

- **Brier Score**: Measures calibration (lower is better, 0-1 range)
- **F1 Score**: Harmonic mean of precision and recall
- **F2 Score**: Weighted F-score favoring recall
- **Precision**: True positives / (true positives + false positives)
- **Recall**: True positives / (true positives + false negatives)
- **Calibration Slope**: Regression slope of observed vs predicted
- **Confusion Matrix**: TP, FP, TN, FN counts

Metrics are stored in the `model_metrics` table and accessible via API.

## API Endpoints

### List Models

```bash
GET /models?active_only=true
```

Returns all registered models (active only by default).

### Get Model Details

```bash
GET /models/{model_id}
```

Returns detailed information about a specific model.

### Current Predictions

```bash
GET /predictions/current
```

Returns the latest predictions from all active models.

**Response:**
```json
{
  "timestamp": "2026-08-13T18:00:00Z",
  "predictions": [
    {
      "model": "baseline",
      "probability": 0.65,
      "binary_prediction": true,
      "threshold": 0.5
    }
  ]
}
```

### Prediction History

```bash
GET /predictions/history?model=baseline&start=2026-08-01T00:00:00Z&end=2026-08-13T23:59:59Z
```

Returns historical predictions for a model within a date range.

### Evaluate Model

```bash
POST /predictions/evaluate
```

Evaluate model on custom data without storing predictions.

**Request:**
```json
{
  "model": "baseline",
  "data": [
    {
      "timestamp": "2026-08-13T18:00:00Z",
      "temperature": 15.5,
      "humidity": 80.0,
      "pressure": 1013.25
    }
  ]
}
```

**Response:**
```json
{
  "predictions": [
    {
      "timestamp": "2026-08-13T18:00:00Z",
      "probability": 0.65
    }
  ]
}
```

### Model Metrics

```bash
GET /models/{model_id}/metrics
```

Returns the latest performance metrics for a model.

### Metrics History

```bash
GET /models/{model_id}/metrics/history?start=2026-08-01&end=2026-08-13
```

Returns historical metrics for a model within a date range.

## Testing

### Unit Tests

Test individual components:

```bash
# Test prediction service
pytest backend/tests/test_ml/test_prediction_service.py -v

# Test model cache
pytest backend/tests/test_ml/test_model_cache.py -v

# Test daily task
pytest backend/tests/test_ml/test_daily_task.py -v
```

### Integration Tests

Test complete ML workflow:

```bash
pytest backend/tests/test_integration/test_ml_flow.py -v
```

### Performance Tests

Verify caching performance:

```bash
pytest backend/tests/test_ml/test_model_cache.py::TestModelCache::test_cache_hit_performance -v -s
```

## Deployment Checklist

- [ ] Train and save model files to `models/` directory
- [ ] Register models in database with correct config
- [ ] Verify model features match input data schema
- [ ] Set appropriate classification thresholds
- [ ] Mark production models as `active=True`
- [ ] Test predictions with `/predictions/evaluate` endpoint
- [ ] Verify background task runs successfully
- [ ] Monitor metrics for model degradation
- [ ] Set up alerts for prediction failures

## Troubleshooting

### Model not found
- Verify model is registered in database: `SELECT * FROM models;`
- Check `file_path` in model config points to existing file
- Ensure `active=True` for production models

### Predictions fail
- Check model file is readable and valid pickle
- Verify input features match model's expected features
- Review logs: the application logs to stderr (`logging.basicConfig` in `app/main.py`); there is no file logger

### Cache not working
- Verify singleton: `get_model_cache()` returns same instance
- Check cache isn't being cleared unexpectedly
- Review the cache tests for expected behavior

### Background task not running
- Verify scheduler is started: check logs at startup
- Check timezone configuration (should be UTC)
- Manual trigger: `POST /admin/ml/trigger-daily-task`

### Metrics not calculated
- Verify ground truth data is available
- Check date range matches prediction timestamps
- Review metrics calculator logs

## Security

- **Authentication**: All ML endpoints require valid API keys
- **Permissions**: 
  - `read` scope: List models, get predictions, view metrics
  - `write` scope: Evaluate models on custom data
  - `admin` scope: Trigger background tasks, manage models
- **Rate limiting**: Configurable per API key
- **Input validation**: All inputs validated via Pydantic schemas

## Performance

- **Model caching**: ~20-50x speedup for repeated loads (no disk I/O on cache hits)
- **Database indexing**: Optimized queries on timestamp + model_id
- **Async I/O**: All database operations use async/await
- **Connection pooling**: Efficient database connection reuse

## Future Enhancements

- Real-time predictions via WebSocket
- Model A/B testing framework
- Automated retraining pipeline
- Model performance monitoring dashboard
- Multi-model ensemble predictions
- Feature importance tracking
