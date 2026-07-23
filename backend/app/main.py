from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
import logging

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description="Rain analysis and prediction API"
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
