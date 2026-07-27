"""Predictions API endpoints."""

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime
from typing import Optional
import pandas as pd
import logging

from ..database import get_db
from ..schemas.ml import (
    CurrentPredictionsResponse,
    PredictionResponse,
    PredictionHistoryResponse,
    PredictionHistoryItem,
    EvaluationRequest,
    EvaluationResponse,
    EvaluationPrediction,
)
from ..models.ml import MLModel, Prediction
from ..ml.prediction_service import PredictionService
from ..auth.dependencies import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get("/current", response_model=CurrentPredictionsResponse)
async def get_current_predictions(
    db: AsyncSession = Depends(get_db),
    _api_key = Depends(require_api_key("read")),
):
    """
    Get current predictions from all active models.
    
    Returns the latest predictions from all active models in the system.
    This endpoint shows the most recent prediction timestamp and the
    predictions from each active model at that time.
    
    Returns:
        CurrentPredictionsResponse with timestamp and list of predictions
    
    Raises:
        HTTPException 404: If no predictions are found in the database
    """
    # Get latest timestamp
    result = await db.execute(
        select(Prediction.timestamp)
        .order_by(Prediction.timestamp.desc())
        .limit(1)
    )
    latest_timestamp = result.scalar_one_or_none()
    
    if not latest_timestamp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No predictions found"
        )
    
    logger.info(f"Latest prediction timestamp: {latest_timestamp}")
    
    # Get all predictions for latest timestamp from active models
    result = await db.execute(
        select(Prediction, MLModel)
        .join(MLModel)
        .where(
            and_(
                Prediction.timestamp == latest_timestamp,
                MLModel.active == True
            )
        )
    )
    
    predictions = []
    for pred, model in result:
        predictions.append(
            PredictionResponse(
                model=model.name,
                probability=pred.probability,
                binary_prediction=pred.binary_prediction,
                threshold=pred.threshold,
            )
        )
    
    logger.info(f"Retrieved {len(predictions)} predictions from active models")
    
    return CurrentPredictionsResponse(
        timestamp=latest_timestamp,
        predictions=predictions,
    )


@router.get("/history", response_model=PredictionHistoryResponse)
async def get_prediction_history(
    model: str = Query(..., description="Model name"),
    start: datetime = Query(..., description="Start timestamp (ISO 8601)"),
    end: datetime = Query(..., description="End timestamp (ISO 8601)"),
    db: AsyncSession = Depends(get_db),
    _api_key = Depends(require_api_key("read")),
):
    """
    Get prediction history for a specific model within a date range.
    
    Returns all predictions for the specified model between the start
    and end timestamps (inclusive).
    
    Args:
        model: Name of the model
        start: Start timestamp (ISO 8601 format)
        end: End timestamp (ISO 8601 format)
    
    Returns:
        PredictionHistoryResponse with model name and list of prediction data points
    
    Raises:
        HTTPException 404: If model is not found
    """
    # Get model
    result = await db.execute(
        select(MLModel).where(MLModel.name == model)
    )
    ml_model = result.scalar_one_or_none()
    
    if not ml_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{model}' not found"
        )
    
    logger.info(f"Fetching prediction history for model '{model}' from {start} to {end}")
    
    # Get predictions in range
    result = await db.execute(
        select(Prediction)
        .where(
            and_(
                Prediction.model_id == ml_model.id,
                Prediction.timestamp >= start,
                Prediction.timestamp <= end,
            )
        )
        .order_by(Prediction.timestamp)
    )
    
    predictions = result.scalars().all()
    
    logger.info(f"Retrieved {len(predictions)} predictions for model '{model}'")
    
    return PredictionHistoryResponse(
        model=model,
        data=[
            PredictionHistoryItem(
                timestamp=p.timestamp,
                probability=p.probability,
                binary_prediction=p.binary_prediction,
            )
            for p in predictions
        ],
    )


@router.post("/evaluate", response_model=EvaluationResponse)
async def evaluate_model(
    request: EvaluationRequest,
    db: AsyncSession = Depends(get_db),
    _api_key = Depends(require_api_key("write")),
):
    """
    Evaluate model on provided data without storing predictions.
    
    This endpoint allows you to test a model on custom data without
    storing the predictions in the database. Useful for ad-hoc
    evaluation and testing.
    
    Args:
        request: Evaluation request with model name and data points
    
    Returns:
        EvaluationResponse with predictions for each input data point
    
    Raises:
        HTTPException 404: If model is not found
        HTTPException 400: If data is invalid or empty
    """
    # Get model
    result = await db.execute(
        select(MLModel).where(MLModel.name == request.model)
    )
    ml_model = result.scalar_one_or_none()
    
    if not ml_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{request.model}' not found"
        )
    
    if not request.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Data cannot be empty"
        )
    
    logger.info(f"Evaluating model '{request.model}' on {len(request.data)} data points")
    
    # Convert request data to DataFrame
    data_dicts = [item.model_dump() for item in request.data]
    df = pd.DataFrame(data_dicts)
    timestamps = df["timestamp"].tolist()
    features_df = df.drop(columns=["timestamp"])
    
    # Generate predictions
    service = PredictionService(db)
    try:
        probabilities = service.predict(ml_model.name, features_df)
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prediction failed: {str(e)}"
        )
    
    logger.info(f"Generated {len(probabilities)} predictions")
    
    # Return predictions
    return EvaluationResponse(
        predictions=[
            EvaluationPrediction(timestamp=ts, probability=prob)
            for ts, prob in zip(timestamps, probabilities)
        ]
    )
