from fastapi import APIRouter, FastAPI, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from .config import settings
from .constants import EXEMPT_PATHS
from .database import init_db, close_db, get_db
from .routers import admin, auth, data, predictions, models, reports
from .auth.middleware import auth_middleware
from .ml.daily_task import _daily_task
import logging
import time

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

# Track application start time for uptime calculation
app_start_time = time.time()

# Async scheduler: jobs run as coroutines on the app's own event loop,
# sharing the aiosqlite engine (a sync scheduler + asyncio.run would not)
scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    await init_db()

    # Start APScheduler
    scheduler.add_job(
        _daily_task.run,
        trigger=CronTrigger(hour=0, minute=0, timezone="UTC"),
        id="daily_ml_task",
        name="Daily ML predictions and metrics",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("APScheduler started - daily ML task scheduled for 00:00 UTC")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    scheduler.shutdown()
    logger.info("APScheduler stopped")
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
    
    # Apply security to all endpoints except auth-exempt ones
    for path, path_item in openapi_schema["paths"].items():
        if path not in EXEMPT_PATHS:
            for operation in path_item.values():
                if isinstance(operation, dict) and "operationId" in operation:
                    operation["security"] = [{"APIKeyHeader": []}]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Register authentication middleware
app.middleware("http")(auth_middleware)

# Register routers under the versioned API prefix.
# Health probes and the root info page stay unversioned.
api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(admin.router)
api_v1.include_router(auth.router)
api_v1.include_router(data.router)
api_v1.include_router(models.router)
api_v1.include_router(predictions.router)
api_v1.include_router(reports.router)
app.include_router(api_v1)

@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Health check endpoint with database connectivity test.
    
    Returns the API status, version, and results of health checks including
    database connectivity. This endpoint can be used for monitoring, uptime checks,
    and load balancer health probes.
    
    Returns:
        200 OK if all checks pass
        503 Service Unavailable if any check fails
    """
    checks = {
        "api": "ok",
        "database": "unknown",
        "version": settings.app_version,
        "uptime_seconds": int(time.time() - app_start_time)
    }
    
    # Test database connectivity
    try:
        start_time = time.time()
        await db.execute(text("SELECT 1"))
        latency_ms = int((time.time() - start_time) * 1000)
        checks["database"] = "ok"
        checks["database_latency_ms"] = latency_ms
    except Exception as e:
        logger.error(f"Health check database error: {e}")
        checks["database"] = "error"
        checks["database_error"] = str(e)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "checks": checks
            }
        )
    
    return {
        "status": "healthy",
        "checks": checks
    }

@app.get("/health/live")
async def liveness_check():
    """
    Liveness probe endpoint.
    
    Simple check that returns 200 if the process is running.
    Use this for Kubernetes liveness probes or similar.
    """
    return {"status": "alive"}

@app.get("/health/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """
    Readiness probe endpoint.
    
    Comprehensive check that verifies the service can handle traffic.
    Checks database connectivity and returns 503 if not ready.
    Use this for Kubernetes readiness probes or load balancer health checks.
    """
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "reason": "database_unavailable"
            }
        )
    
    return {"status": "ready"}

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


