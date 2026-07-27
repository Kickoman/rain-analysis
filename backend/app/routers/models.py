"""Models API endpoints."""

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import date
from typing import Optional
import logging

from ..database import get_db
from ..schemas.ml import (
    MLModelListResponse,
    MLModelResponse,
    LatestMetricsResponse,
    MetricsHistoryResponse,
    ModelMetricsResponse,
    ConfusionMatrix,
)
from ..models.ml import MLModel, ModelMetric
from ..auth.dependencies import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=MLModelListResponse)
async def list_models(
    active_only: bool = Query(True, description="Filter active models only"),
    db: AsyncSession = Depends(get_db),
    _api_key = Depends(require_api_key("read")),
):
    """
    List all registered ML models.
    
    Returns a list of all ML models in the system. By default, only active
    models are returned, but this can be controlled with the active_only parameter.
    
    Args:
        active_only: If True, only return active models (default: True)
        db: Database session (injected)
        _api_key: API key for authentication (injected)
    
    Returns:
        MLModelListResponse with list of models
    """
    query = select(MLModel)
    if active_only:
        query = query.where(MLModel.active == True)
    
    result = await db.execute(query.order_by(MLModel.name))
    models = result.scalars().all()
    
    return MLModelListResponse(
        models=[
            MLModelResponse(
                id=m.id,
                name=m.name,
                version=m.version,
                description=m.description,
                config=m.config if m.config is not None else {},
                active=m.active,
                created_at=m.created_at,
            )
            for m in models
        ]
    )


@router.get("/{model_id}", response_model=MLModelResponse)
async def get_model(
    model_id: int,
    db: AsyncSession = Depends(get_db),
    _api_key = Depends(require_api_key("read")),
):
    """
    Get specific model details.
    
    Returns detailed information about a specific ML model by its ID.
    
    Args:
        model_id: The ID of the model to retrieve
        db: Database session (injected)
        _api_key: API key for authentication (injected)
    
    Returns:
        MLModelResponse with model details
    
    Raises:
        HTTPException 404: If the model is not found
    """
    result = await db.execute(
        select(MLModel).where(MLModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model {model_id} not found"
        )
    
    return MLModelResponse(
        id=model.id,
        name=model.name,
        version=model.version,
        description=model.description,
        config=model.config if model.config is not None else {},
        active=model.active,
        created_at=model.created_at,
    )


@router.get("/{model_id}/metrics", response_model=LatestMetricsResponse)
async def get_latest_metrics(
    model_id: int,
    db: AsyncSession = Depends(get_db),
    _api_key = Depends(require_api_key("read")),
):
    """
    Get latest metrics for a model.
    
    Returns the most recent performance metrics for the specified model.
    Metrics include Brier score, F1/F2 scores, precision, recall, calibration,
    and confusion matrix.
    
    Args:
        model_id: The ID of the model
        db: Database session (injected)
        _api_key: API key for authentication (injected)
    
    Returns:
        LatestMetricsResponse with the latest metrics
    
    Raises:
        HTTPException 404: If the model is not found or has no metrics
    """
    # Get model
    result = await db.execute(
        select(MLModel).where(MLModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model {model_id} not found"
        )
    
    # Get latest metrics
    result = await db.execute(
        select(ModelMetric)
        .where(ModelMetric.model_id == model_id)
        .order_by(ModelMetric.date.desc())
        .limit(1)
    )
    latest_metric = result.scalar_one_or_none()
    
    if not latest_metric:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No metrics found for model {model_id}"
        )
    
    # Convert confusion_matrix dict to ConfusionMatrix if present
    confusion_matrix = None
    if latest_metric.confusion_matrix:
        confusion_matrix = ConfusionMatrix(**latest_metric.confusion_matrix)
    
    return LatestMetricsResponse(
        model=model.name,
        latest_metrics=ModelMetricsResponse(
            date=latest_metric.date,
            brier_score=latest_metric.brier_score,
            f1_score=latest_metric.f1_score,
            f2_score=latest_metric.f2_score,
            precision_score=latest_metric.precision_score,
            recall=latest_metric.recall,
            calibration_slope=latest_metric.calibration_slope,
            threshold=latest_metric.threshold,
            confusion_matrix=confusion_matrix,
        ),
    )


@router.get("/{model_id}/metrics/history", response_model=MetricsHistoryResponse)
async def get_metrics_history(
    model_id: int,
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: date = Query(..., description="End date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    _api_key = Depends(require_api_key("read")),
):
    """
    Get metrics history for a model.
    
    Returns historical performance metrics for the specified model within
    a given date range. This allows tracking model performance over time.
    
    Args:
        model_id: The ID of the model
        start: Start date (inclusive) in YYYY-MM-DD format
        end: End date (inclusive) in YYYY-MM-DD format
        db: Database session (injected)
        _api_key: API key for authentication (injected)
    
    Returns:
        MetricsHistoryResponse with historical metrics
    
    Raises:
        HTTPException 404: If the model is not found
        HTTPException 400: If start date is after end date
    """
    # Validate date range
    if start > end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start date must be before or equal to end date"
        )
    
    # Get model
    result = await db.execute(
        select(MLModel).where(MLModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model {model_id} not found"
        )
    
    # Get metrics in range
    result = await db.execute(
        select(ModelMetric)
        .where(
            and_(
                ModelMetric.model_id == model_id,
                ModelMetric.date >= start,
                ModelMetric.date <= end,
            )
        )
        .order_by(ModelMetric.date)
    )
    
    metrics = result.scalars().all()
    
    # Convert metrics to response format
    history = []
    for m in metrics:
        confusion_matrix = None
        if m.confusion_matrix:
            confusion_matrix = ConfusionMatrix(**m.confusion_matrix)
        
        history.append(
            ModelMetricsResponse(
                date=m.date,
                brier_score=m.brier_score,
                f1_score=m.f1_score,
                f2_score=m.f2_score,
                precision_score=m.precision_score,
                recall=m.recall,
                calibration_slope=m.calibration_slope,
                threshold=m.threshold,
                confusion_matrix=confusion_matrix,
            )
        )
    
    return MetricsHistoryResponse(
        model=model.name,
        history=history,
    )
