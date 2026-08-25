"""Prediction service for generating and storing model predictions.

Orchestrates:
- Loading models from cache
- Generating predictions on input features
- Storing predictions to database
- Managing model activation status
"""

import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
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
    
    def _load_estimator(self, model) -> Any:
        """Resolve the estimator for an MLModel row.

        config["kind"] selects the backend:
          - "sklearn" (default): pickle loaded via ModelCache; the file is
            config["file_path"] (relative paths resolve against models_dir)
            or {models_dir}/{name}.pkl
          - "rainlib": shared rainlib formula model, no pickle involved
        """
        config = model.config or {}
        kind = config.get("kind", "sklearn")
        if kind == "rainlib":
            from .rainlib_models import get_rainlib_adapter
            return get_rainlib_adapter(config)
        if kind != "sklearn":
            raise ValueError(f"Unknown model kind {kind!r} for model '{model.name}'")

        file_path = config.get("file_path")
        if file_path is not None:
            file_path = Path(file_path)
            if not file_path.is_absolute():
                file_path = self.model_cache.models_dir / file_path
        return self.model_cache.load_model(model.name, file_path=file_path)

    def predict(self, model, features: pd.DataFrame) -> List[float]:
        """Generate predictions for given features.

        Args:
            model: MLModel row (name + config drive estimator resolution)
            features: DataFrame with feature columns matching model expectations

        Returns:
            List of probability predictions (floats between 0 and 1)

        Raises:
            FileNotFoundError: If model pickle file not found
            AttributeError: If model doesn't have predict_proba method

        Note: this is synchronous CPU work — call it via asyncio.to_thread
        from async code (predict_async does exactly that).
        """
        config = model.config or {}

        # The config's feature list is the serving contract: select and order
        # columns to match what the estimator was fitted on.
        feature_names = config.get("features")
        if feature_names:
            missing = [f for f in feature_names if f not in features.columns]
            if missing:
                raise ValueError(
                    f"Model '{model.name}' requires missing features: {missing}"
                )
            features = features[feature_names]

        estimator = self._load_estimator(model)

        logger.debug(f"Generating predictions with model '{model.name}' on {len(features)} samples")

        if hasattr(estimator, 'predict_proba'):
            probabilities = estimator.predict_proba(features)
            if probabilities.ndim == 2:
                # Shape (n_samples, n_classes) -> take positive class
                probabilities = probabilities[:, 1]
        elif hasattr(estimator, 'predict'):
            # Fallback: direct predict (may return binary or probability)
            probabilities = estimator.predict(features)
        else:
            raise AttributeError(f"Model '{model.name}' has no predict_proba or predict method")

        return probabilities.tolist()

    async def predict_async(self, model, features: pd.DataFrame) -> List[float]:
        """Run predict() off the event loop."""
        return await asyncio.to_thread(self.predict, model, features)
    
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
        probabilities = await self.predict_async(model, features)
        
        # Get threshold from config or parameter
        if threshold is None:
            threshold = model.config.get("threshold", 0.5) if model.config else 0.5
        
        logger.debug(f"Using threshold={threshold} for binary classification")
        
        # Store predictions (upsert: re-running a day refreshes rows in place)
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        rows = [
            {
                "model_id": model_id,
                "timestamp": timestamp,
                "probability": prob,
                "threshold": threshold,
                "binary_prediction": prob >= threshold,
            }
            for timestamp, prob in zip(timestamps, probabilities)
        ]
        stmt = sqlite_insert(Prediction).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["model_id", "timestamp"],
            set_={
                "probability": stmt.excluded.probability,
                "threshold": stmt.excluded.threshold,
                "binary_prediction": stmt.excluded.binary_prediction,
            },
        )
        await self.db.execute(stmt)
        await self.db.commit()
        logger.info(f"Stored {len(rows)} predictions for model '{model.name}'")

        return len(rows)
    
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
