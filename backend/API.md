# Rain Analysis API Documentation

## Overview

The Rain Analysis API provides endpoints for weather prediction, model management, and system administration.

Most endpoints require authentication via API keys. The health-check endpoints (`/health`, `/health/live`, `/health/ready`) and the interactive docs (`/docs`, `/openapi.json`, `/redoc`) are public and require no API key.

## Authentication

Authenticated requests require an `X-API-Key` header:

```bash
curl -H "X-API-Key: your-api-key-here" https://api.example.com/models
```

### API Key Scopes

- **read**: Access prediction data and model information
- **write**: Evaluate models on custom data
- **admin**: Full access including key management and system administration

## Base URL

```
http://localhost:8000
```

## Health Endpoints

### GET /health

Check API health status, including database connectivity.

**Authentication:** Not required

**Response:**
```json
{
  "status": "healthy",
  "checks": {
    "api": "ok",
    "database": "ok",
    "version": "1.0.0",
    "uptime_seconds": 12345,
    "database_latency_ms": 2
  }
}
```

If the database check fails, the response is `503 Service Unavailable`:
```json
{
  "status": "unhealthy",
  "checks": {
    "api": "ok",
    "database": "error",
    "version": "1.0.0",
    "uptime_seconds": 12345,
    "database_error": "connection refused"
  }
}
```

---

### GET /health/live

Liveness probe. Returns 200 if the process is running.

**Authentication:** Not required

**Response:**
```json
{
  "status": "alive"
}
```

---

### GET /health/ready

Readiness probe. Verifies database connectivity and returns 503 if not ready.

**Authentication:** Not required

**Response:**
```json
{
  "status": "ready"
}
```

If the database is unavailable, the response is `503 Service Unavailable`:
```json
{
  "status": "not_ready",
  "reason": "database_unavailable"
}
```

---

## Authentication Endpoint

### GET /auth/check

Check the validity of the provided API key and return its scope and rate-limit status.

**Authentication:** Valid API key required

**Response:**
```json
{
  "valid": true,
  "key_id": 1,
  "owner": "test_user",
  "scope": "read",
  "rate_limits": {
    "rpm": 100,
    "rph": 1000,
    "rpd": 10000
  },
  "remaining": {
    "rpm": 99,
    "rph": 999,
    "rpd": 9999
  },
  "expires_at": null
}
```

---

## ML Endpoints

### Predictions

#### GET /predictions/current

Get latest predictions from all active models.

**Authentication:** Read API key required

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
    },
    {
      "model": "ensemble",
      "probability": 0.58,
      "binary_prediction": true,
      "threshold": 0.5
    }
  ]
}
```

**Status Codes:**
- `200 OK`: Predictions retrieved successfully
- `401 Unauthorized`: Missing or invalid API key
- `404 Not Found`: No predictions available

---

#### GET /predictions/history

Get prediction history for a specific model.

**Authentication:** Read API key required

**Parameters:**
- `model` (query, required): Model name
- `start` (query, required): Start timestamp (ISO 8601)
- `end` (query, required): End timestamp (ISO 8601)

**Example:**
```bash
curl -H "X-API-Key: $READ_KEY" \
  "http://localhost:8000/predictions/history?model=baseline&start=2026-08-01T00:00:00Z&end=2026-08-13T23:59:59Z"
```

**Response:**
```json
{
  "model": "baseline",
  "data": [
    {
      "timestamp": "2026-08-01T00:00:00Z",
      "probability": 0.45,
      "binary_prediction": false
    },
    {
      "timestamp": "2026-08-01T01:00:00Z",
      "probability": 0.62,
      "binary_prediction": true
    }
  ]
}
```

**Status Codes:**
- `200 OK`: History retrieved successfully
- `401 Unauthorized`: Missing or invalid API key
- `404 Not Found`: Model not found

---

#### POST /predictions/evaluate

Evaluate model on provided data without storing predictions.

**Authentication:** Write API key required

**Request Body:**
```json
{
  "model": "baseline",
  "data": [
    {
      "timestamp": "2026-08-13T18:00:00Z",
      "temperature": 15.5,
      "humidity": 80.0,
      "pressure": 1013.25
    },
    {
      "timestamp": "2026-08-13T19:00:00Z",
      "temperature": 16.0,
      "humidity": 75.0,
      "pressure": 1012.80
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
    },
    {
      "timestamp": "2026-08-13T19:00:00Z",
      "probability": 0.52
    }
  ]
}
```

**Status Codes:**
- `200 OK`: Evaluation successful
- `400 Bad Request`: Invalid data or empty data array
- `401 Unauthorized`: Missing or invalid API key
- `403 Forbidden`: Insufficient permissions (read key used on a write endpoint)
- `404 Not Found`: Model not found
- `500 Internal Server Error`: Prediction failed

**Example:**
```bash
curl -X POST \
  -H "X-API-Key: $WRITE_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "baseline",
    "data": [
      {
        "timestamp": "2026-08-13T18:00:00Z",
        "temperature": 15.5,
        "humidity": 80.0,
        "pressure": 1013.25
      }
    ]
  }' \
  http://localhost:8000/predictions/evaluate
```

---

### Models

#### GET /models

List all registered models.

**Authentication:** Read API key required

**Parameters:**
- `active_only` (query, optional, default: true): Filter active models only

**Example:**
```bash
# Get active models only
curl -H "X-API-Key: $READ_KEY" http://localhost:8000/models

# Get all models including inactive
curl -H "X-API-Key: $READ_KEY" http://localhost:8000/models?active_only=false
```

**Response:**
```json
{
  "models": [
    {
      "id": 1,
      "name": "baseline",
      "version": "v1.0",
      "description": "Temperature + humidity baseline model",
      "config": {
        "features": ["temperature", "humidity", "pressure"],
        "threshold": 0.5,
        "file_path": "models/baseline.pkl"
      },
      "active": true,
      "created_at": "2026-07-20T10:00:00Z"
    }
  ]
}
```

**Status Codes:**
- `200 OK`: Models retrieved successfully
- `401 Unauthorized`: Missing or invalid API key

---

#### GET /models/{model_id}

Get specific model details.

**Authentication:** Read API key required

**Parameters:**
- `model_id` (path, required): Model ID

**Example:**
```bash
curl -H "X-API-Key: $READ_KEY" http://localhost:8000/models/1
```

**Response:**
```json
{
  "id": 1,
  "name": "baseline",
  "version": "v1.0",
  "description": "Temperature + humidity baseline model",
  "config": {
    "features": ["temperature", "humidity", "pressure"],
    "threshold": 0.5,
    "file_path": "models/baseline.pkl"
  },
  "active": true,
  "created_at": "2026-07-20T10:00:00Z"
}
```

**Status Codes:**
- `200 OK`: Model retrieved successfully
- `401 Unauthorized`: Missing or invalid API key
- `404 Not Found`: Model not found

---

#### GET /models/{model_id}/metrics

Get latest performance metrics for a model.

**Authentication:** Read API key required

**Parameters:**
- `model_id` (path, required): Model ID

**Example:**
```bash
curl -H "X-API-Key: $READ_KEY" http://localhost:8000/models/1/metrics
```

**Response:**
```json
{
  "model": "baseline",
  "latest_metrics": {
    "date": "2026-08-13",
    "brier_score": 0.15,
    "f1_score": 0.82,
    "f2_score": 0.85,
    "precision_score": 0.80,
    "recall": 0.85,
    "calibration_slope": 0.95,
    "threshold": 0.5,
    "confusion_matrix": {
      "TP": 45,
      "FP": 10,
      "TN": 85,
      "FN": 8
    }
  }
}
```

**Metrics Explanation:**
- **Brier Score**: Measures prediction accuracy and calibration (0-1, lower is better)
- **F1 Score**: Harmonic mean of precision and recall (0-1, higher is better)
- **F2 Score**: Weighted F-score favoring recall (0-1, higher is better)
- **Precision**: Proportion of positive predictions that are correct
- **Recall**: Proportion of actual positives that are detected
- **Calibration Slope**: How well probabilities match observed frequencies (1.0 is perfect)
- **Confusion Matrix**: Breakdown of prediction outcomes (`TP`, `FP`, `TN`, `FN`)

**Status Codes:**
- `200 OK`: Metrics retrieved successfully
- `401 Unauthorized`: Missing or invalid API key
- `404 Not Found`: Model not found or no metrics available

---

#### GET /models/{model_id}/metrics/history

Get metrics history for a model.

**Authentication:** Read API key required

**Parameters:**
- `model_id` (path, required): Model ID
- `start` (query, required): Start date (YYYY-MM-DD)
- `end` (query, required): End date (YYYY-MM-DD)

**Example:**
```bash
curl -H "X-API-Key: $READ_KEY" \
  "http://localhost:8000/models/1/metrics/history?start=2026-08-01&end=2026-08-13"
```

**Response:**
```json
{
  "model": "baseline",
  "history": [
    {
      "date": "2026-08-01",
      "brier_score": 0.16,
      "f1_score": 0.80,
      "f2_score": 0.83,
      "precision_score": 0.78,
      "recall": 0.83,
      "calibration_slope": 0.93,
      "threshold": 0.5,
      "confusion_matrix": {
        "TP": 42,
        "FP": 12,
        "TN": 82,
        "FN": 10
      }
    },
    {
      "date": "2026-08-13",
      "brier_score": 0.15,
      "f1_score": 0.82,
      "f2_score": 0.85,
      "precision_score": 0.80,
      "recall": 0.85,
      "calibration_slope": 0.95,
      "threshold": 0.5,
      "confusion_matrix": {
        "TP": 45,
        "FP": 10,
        "TN": 85,
        "FN": 8
      }
    }
  ]
}
```

**Status Codes:**
- `200 OK`: History retrieved successfully
- `400 Bad Request`: Invalid date range (start > end)
- `401 Unauthorized`: Missing or invalid API key
- `404 Not Found`: Model not found

---

## Admin Endpoints

### API Key Management

#### POST /admin/keys

Create a new API key.

**Authentication:** Admin API key required

**Request Body:**
```json
{
  "owner": "production-read",
  "description": "Production read key",
  "scope": "read",
  "rate_limit_rpm": 100,
  "rate_limit_rph": 1000,
  "rate_limit_rpd": 10000,
  "environment": "live",
  "expires_at": null
}
```

**Response:**
```json
{
  "key": "ra_live_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
  "key_info": {
    "id": 5,
    "key_prefix": "ra_live_a1b2c3",
    "owner": "production-read",
    "description": "Production read key",
    "scope": "read",
    "rate_limit_rpm": 100,
    "rate_limit_rph": 1000,
    "rate_limit_rpd": 10000,
    "is_active": true,
    "created_at": "2026-08-13T18:00:00Z",
    "expires_at": null,
    "last_used_at": null
  }
}
```

**Important:** Save the `key` value - it cannot be retrieved later!

---

#### GET /admin/keys

List all API keys.

**Authentication:** Admin API key required

**Response:**
```json
[
  {
    "id": 1,
    "key_prefix": "ra_live_abc123",
    "owner": "admin",
    "description": "Admin key",
    "scope": "admin",
    "rate_limit_rpm": 1000,
    "rate_limit_rph": 10000,
    "rate_limit_rpd": 100000,
    "is_active": true,
    "created_at": "2026-07-20T10:00:00Z",
    "expires_at": null,
    "last_used_at": "2026-08-13T17:45:00Z"
  }
]
```

---

#### GET /admin/keys/{key_id}

Get details of a specific API key.

**Authentication:** Admin API key required

**Parameters:**
- `key_id` (path, required): API key ID

**Response:**
```json
{
  "id": 1,
  "key_prefix": "ra_live_abc123",
  "owner": "admin",
  "description": "Admin key",
  "scope": "admin",
  "rate_limit_rpm": 1000,
  "rate_limit_rph": 10000,
  "rate_limit_rpd": 100000,
  "is_active": true,
  "created_at": "2026-07-20T10:00:00Z",
  "expires_at": null,
  "last_used_at": "2026-08-13T17:45:00Z"
}
```

**Status Codes:**
- `200 OK`: API key retrieved successfully
- `401 Unauthorized`: Missing or invalid API key
- `403 Forbidden`: Non-admin key
- `404 Not Found`: API key not found

---

#### PATCH /admin/keys/{key_id}

Update API key rate limits or active status.

**Authentication:** Admin API key required

**Request Body:**
```json
{
  "rate_limit_rpm": 200,
  "is_active": false
}
```

---

#### DELETE /admin/keys/{key_id}

Deactivate an API key (sets `is_active=False`). The record is not deleted.

**Authentication:** Admin API key required

**Response:** `204 No Content`

---

### System Administration

#### POST /admin/ml/trigger-daily-task

Manually trigger the daily ML prediction task.

**Authentication:** Admin API key required

**Example:**
```bash
curl -X POST \
  -H "X-API-Key: $ADMIN_KEY" \
  http://localhost:8000/admin/ml/trigger-daily-task
```

**Response:**
```json
{
  "message": "Daily ML task triggered successfully",
  "status": "running_in_background"
}
```

---

## Error Responses

All errors follow a consistent format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

### Common Status Codes

- `200 OK`: Request successful
- `400 Bad Request`: Invalid request parameters or body
- `401 Unauthorized`: Missing or invalid API key
- `403 Forbidden`: Insufficient permissions (valid key, but scope too low)
- `404 Not Found`: Resource not found
- `429 Too Many Requests`: Rate limit exceeded
- `500 Internal Server Error`: Server error

### Rate Limiting

When rate limit is exceeded:

```json
{
  "detail": "Rate limit exceeded"
}
```

Rate limits are configurable per API key:
- RPM: Requests per minute
- RPH: Requests per hour
- RPD: Requests per day

---

## Examples

### Complete Workflow Example

```bash
# 1. List available models
curl -H "X-API-Key: $READ_KEY" \
  http://localhost:8000/models

# 2. Get current predictions
curl -H "X-API-Key: $READ_KEY" \
  http://localhost:8000/predictions/current

# 3. Get prediction history for last 7 days
START=$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%SZ)
END=$(date -u +%Y-%m-%dT%H:%M:%SZ)
curl -H "X-API-Key: $READ_KEY" \
  "http://localhost:8000/predictions/history?model=baseline&start=$START&end=$END"

# 4. Get model metrics
curl -H "X-API-Key: $READ_KEY" \
  http://localhost:8000/models/1/metrics

# 5. Evaluate model on custom data
curl -X POST \
  -H "X-API-Key: $WRITE_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "baseline",
    "data": [
      {
        "timestamp": "2026-08-13T18:00:00Z",
        "temperature": 15.5,
        "humidity": 80.0,
        "pressure": 1013.25
      }
    ]
  }' \
  http://localhost:8000/predictions/evaluate
```

---

## Client Libraries

### Python

```python
import httpx
from datetime import datetime, timedelta

API_KEY = "your-api-key"
BASE_URL = "http://localhost:8000"

async def get_current_predictions():
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/predictions/current",
            headers={"X-API-Key": API_KEY}
        )
        return response.json()

async def evaluate_model(model_name, features):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/predictions/evaluate",
            headers={"X-API-Key": API_KEY},
            json={"model": model_name, "data": features}
        )
        return response.json()
```

### JavaScript

```javascript
const API_KEY = 'your-api-key';
const BASE_URL = 'http://localhost:8000';

async function getCurrentPredictions() {
  const response = await fetch(`${BASE_URL}/predictions/current`, {
    headers: {
      'X-API-Key': API_KEY
    }
  });
  return response.json();
}

async function evaluateModel(modelName, features) {
  const response = await fetch(`${BASE_URL}/predictions/evaluate`, {
    method: 'POST',
    headers: {
      'X-API-Key': API_KEY,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      model: modelName,
      data: features
    })
  });
  return response.json();
}
```

---

## Best Practices

1. **API Key Security**
   - Never commit API keys to version control
   - Use environment variables for API keys
   - Rotate keys regularly
   - Use separate keys for different environments

2. **Rate Limiting**
   - Implement exponential backoff for retries
   - Cache frequently accessed data
   - Use appropriate rate limits for your use case

3. **Error Handling**
   - Always check response status codes
   - Implement proper error handling for network failures
   - Log errors for debugging

4. **Performance**
   - Use connection pooling for multiple requests
   - Implement client-side caching where appropriate
   - Batch requests when possible

---

## Support

For issues or questions:
- GitHub Issues: https://github.com/Kickoman/rain-analysis/issues
- Documentation: See `backend/ML_INTEGRATION.md` for ML system details
