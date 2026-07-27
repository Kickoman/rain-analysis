from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager
from .config import settings
from .database import init_db, close_db
from . import schemas
from .routers import admin, auth, predictions
from .auth.middleware import auth_middleware
from datetime import datetime
import logging

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    await init_db()
    yield
    logger.info("Shutting down...")
    await close_db()

app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description="Rain analysis and prediction API with API key authentication",
    lifespan=lifespan
)

# Custom OpenAPI schema with security definitions
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    
    # Add security scheme
    openapi_schema["components"]["securitySchemes"] = {
        "APIKeyHeader": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API key for authentication. Format: ra_live_..."
        }
    }
    
    # Apply security to all endpoints except /docs, /openapi.json, /redoc
    for path, path_item in openapi_schema["paths"].items():
        if path not in ["/docs", "/openapi.json", "/redoc"]:
            for operation in path_item.values():
                if isinstance(operation, dict) and "operationId" in operation:
                    operation["security"] = [{"APIKeyHeader": []}]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register authentication middleware
app.middleware("http")(auth_middleware)

# Register routers
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(predictions.router)

@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    
    Returns the API status and version. This endpoint can be used for monitoring
    and uptime checks.
    """
    return {
        "status": "healthy",
        "version": settings.app_version
    }

@app.get("/")
async def root():
    """
    API root endpoint.
    
    Returns basic information about the API including links to documentation.
    """
    return {
        "message": "Rain Analysis API",
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
        "authentication": "Include X-API-Key header with your API key"
    }


# Test endpoints for schema validation
@app.post("/test/sensor", response_model=schemas.SensorResponse, tags=["Testing"])
async def test_sensor_create(sensor: schemas.SensorCreate):
    """Test endpoint for Sensor schema validation."""
    return schemas.SensorResponse(
        id=1,
        created_at=datetime.now(),
        **sensor.model_dump()
    )


@app.post("/test/measurement", response_model=schemas.MeasurementResponse, tags=["Testing"])
async def test_measurement_create(measurement: schemas.MeasurementCreate):
    """Test endpoint for Measurement schema validation."""
    return schemas.MeasurementResponse(
        id=1,
        **measurement.model_dump()
    )


@app.post("/test/ml-model", response_model=schemas.MLModelResponse, tags=["Testing"])
async def test_ml_model_create(ml_model: schemas.MLModelCreate):
    """Test endpoint for MLModel schema validation."""
    return schemas.MLModelResponse(
        id=1,
        created_at=datetime.now(),
        **ml_model.model_dump()
    )


@app.post("/test/prediction", response_model=schemas.PredictionResponse, tags=["Testing"])
async def test_prediction_create(prediction: schemas.PredictionCreate):
    """Test endpoint for Prediction schema validation."""
    return schemas.PredictionResponse(
        id=1,
        created_at=datetime.now(),
        **prediction.model_dump()
    )


@app.post("/test/model-metric", response_model=schemas.ModelMetricResponse, tags=["Testing"])
async def test_model_metric_create(metric: schemas.ModelMetricCreate):
    """Test endpoint for ModelMetric schema validation."""
    return schemas.ModelMetricResponse(
        id=1,
        created_at=datetime.now(),
        **metric.model_dump()
    )


@app.get("/test/paginated", response_model=schemas.PaginatedResponse[schemas.SensorResponse], tags=["Testing"])
async def test_paginated_response():
    """Test endpoint for PaginatedResponse schema."""
    sensors = [
        schemas.SensorResponse(
            id=1,
            name="Temperature",
            unit="°C",
            sensor_type="numeric",
            description="Temperature sensor",
            created_at=datetime.now()
        ),
        schemas.SensorResponse(
            id=2,
            name="Humidity",
            unit="%",
            sensor_type="numeric",
            description="Humidity sensor",
            created_at=datetime.now()
        )
    ]
    return schemas.PaginatedResponse.create(
        items=sensors,
        total=10,
        page=1,
        page_size=2
    )


@app.get("/test/error", response_model=schemas.ErrorResponse, tags=["Testing"])
async def test_error_response():
    """Test endpoint for ErrorResponse schema."""
    return schemas.ErrorResponse(
        error="test_error",
        message="This is a test error message",
        detail="Additional error details for debugging",
        path="/test/error"
    )
