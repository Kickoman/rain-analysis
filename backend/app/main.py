from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from .config import settings
from .database import init_db, close_db
import logging

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up...")
    await init_db()
    yield
    # Shutdown
    logger.info("Shutting down...")
    await close_db()

app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description="Rain analysis and prediction API",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": settings.app_version
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Rain Analysis API",
        "docs": "/docs",
        "health": "/health"
    }
