"""Prediction service for generating and storing model predictions.

Orchestrates:
- Loading models from cache
- Generating predictions on input features
- Storing predictions to database
- Managing model activation status
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)


class PredictionService:
    """Service for generating and storing predictions.
    
    Provides high-level API for:
    - Querying active models
    - Generating predictions from features
    - Storing predictions to database with metadata
    
    Example:
        async with get_db_session() as session:
            service = PredictionService(session)
            models = await service.get_active_models()
            for model in models:
                predictions = await service.predict_and_store(
                    model_id=model.id,
                    features=feature_df,
                    timestamps=timestamp_list
                )
    """
    
    def __init__(self, db: AsyncSession, models_dir: Optional[str] = None):
        """Initialize prediction service.
        
        Args:
            db: Async database session
            models_dir: Optional path to models directory (for cache initialization)
        """
        self.db = db
        # Import locally to avoid circular dependency
        from .model_loader import get_model_cache
        self.model_cache = get_model_cache(models_dir)
    
    async def get_active_models(self):
        """Get all active models from database.
        
        Returns:
            List of MLModel instances with active=True
        """
        from ..models.ml import MLModel
        result = await self.db.execute(
            select(MLModel).where(MLModel.active == True)
        )
        models = result.scalars().all()
        logger.info(f"Retrieved {len(models)} active models")
        return models
    
    async def get_model(self, model_id: int):
        """Get model by ID.
        
        Args:
            model_id: Database ID of model
        
        Returns:
            MLModel instance or None if not found
        """
        from ..models.ml import MLModel
        result = await self.db.execute(
            select(MLModel).where(MLModel.id == model_id)
        )
        return result.scalar_one_or_none()
    
    def predict(self, model_name: str, features: pd.DataFrame) -> List[float]:
        """Generate predictions for given features.
        
        Args:
            model_name: Name of model to load from cache
            features: DataFrame with feature columns matching model expectations
        
        Returns:
            List of probability predictions (floats between 0 and 1)
        
        Raises:
            FileNotFoundError: If model pickle file not found
            AttributeError: If model doesn't have predict_proba method
        """
        # Load model from cache
        model = self.model_cache.load_model(model_name)
        logger.debug(f"Generating predictions with model '{model_name}' on {len(features)} samples")
        
        # Generate predictions
        # Assume model has predict_proba method returning probabilities
        if hasattr(model, 'predict_proba'):
            # Binary classification: return probability of positive class
            probabilities = model.predict_proba(features)
            if probabilities.ndim == 2:
                # Shape (n_samples, n_classes) -> take positive class
                probabilities = probabilities[:, 1]
        elif hasattr(model, 'predict'):
            # Fallback: direct predict (may return binary or probability)
            probabilities = model.predict(features)
        else:
            raise AttributeError(f"Model '{model_name}' has no predict_proba or predict method")
        
        return probabilities.tolist()
    
    async def predict_and_store(
        self,
        model_id: int,
        features: pd.DataFrame,
        timestamps: List[datetime],
        threshold: Optional[float] = None
    ) -> int:
        """Generate predictions and store in database.
        
        Args:
            model_id: Database ID of model
            features: Feature DataFrame for prediction
            timestamps: List of timestamps corresponding to each feature row
            threshold: Optional threshold override (defaults to model.config.threshold)
        
        Returns:
            Number of predictions stored
        
        Raises:
            ValueError: If model not found or timestamps length mismatch
        """
        from ..models.ml import Prediction
        
        if len(features) != len(timestamps):
            raise ValueError(
                f"Features ({len(features)}) and timestamps ({len(timestamps)}) length mismatch"
            )
        
        # Get model from database
        model = await self.get_model(model_id)
        if model is None:
            raise ValueError(f"Model with id={model_id} not found")
        
        logger.info(f"Generating predictions for model '{model.name}' (id={model_id})")
        
        # Generate predictions
        probabilities = self.predict(model.name, features)
        
        # Get threshold from config or parameter
        if threshold is None:
            threshold = model.config.get("threshold", 0.5) if model.config else 0.5
        
        logger.debug(f"Using threshold={threshold} for binary classification")
        
        # Store predictions
        predictions_created = 0
        for timestamp, prob in zip(timestamps, probabilities):
            prediction = Prediction(
                model_id=model_id,
                timestamp=timestamp,
                probability=prob,
                threshold=threshold,
                binary_prediction=prob >= threshold
            )
            self.db.add(prediction)
            predictions_created += 1
        
        await self.db.commit()
        logger.info(f"Stored {predictions_created} predictions for model '{model.name}'")
        
        return predictions_created
    
    async def get_predictions(
        self,
        model_id: int,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000
    ):
        """Retrieve predictions for a model within time range.
        
        Args:
            model_id: Database ID of model
            start_time: Optional start timestamp (inclusive)
            end_time: Optional end timestamp (inclusive)
            limit: Maximum number of predictions to return
        
        Returns:
            List of Prediction objects ordered by timestamp
        """
        from ..models.ml import Prediction
        
        query = select(Prediction).where(Prediction.model_id == model_id)
        
        if start_time:
            query = query.where(Prediction.timestamp >= start_time)
        if end_time:
            query = query.where(Prediction.timestamp <= end_time)
        
        query = query.order_by(Prediction.timestamp).limit(limit)
        
        result = await self.db.execute(query)
        predictions = result.scalars().all()
        
        logger.debug(f"Retrieved {len(predictions)} predictions for model_id={model_id}")
        return predictions
