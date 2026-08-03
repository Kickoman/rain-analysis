"""
Metrics calculator for model performance evaluation.

Calculates daily metrics for ML models by comparing predictions with ground truth.
"""

from datetime import date, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import numpy as np
from sklearn.metrics import (
    brier_score_loss,
    f1_score,
    fbeta_score,
    precision_score,
    recall_score,
    confusion_matrix,
)
import logging

from ..models.ml import Prediction

logger = logging.getLogger(__name__)


class MetricsCalculator:
    """Calculate model performance metrics by comparing predictions with ground truth."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def calculate_daily_metrics(
        self, 
        model_id: int, 
        target_date: date
    ) -> Optional[Dict[str, Any]]:
        """
        Calculate metrics for a specific date.
        
        Args:
            model_id: ID of the model to calculate metrics for
            target_date: Date to calculate metrics for
            
        Returns:
            Dictionary with metrics or None if insufficient data
        """
        
        # Get predictions for the date
        result = await self.db.execute(
            select(Prediction)
            .where(
                and_(
                    Prediction.model_id == model_id,
                    Prediction.timestamp >= target_date,
                    Prediction.timestamp < target_date + timedelta(days=1),
                )
            )
            .order_by(Prediction.timestamp)
        )
        predictions = result.scalars().all()
        
        if not predictions:
            logger.warning(f"No predictions found for model {model_id} on {target_date}")
            return None
        
        logger.info(f"Found {len(predictions)} predictions for model {model_id} on {target_date}")
        
        # TODO: Fetch ground truth from weather_data table or external API
        # For now, we don't have ground truth data, so we return None
        # When ground truth becomes available, uncomment and implement:
        
        # y_true = await self._fetch_ground_truth(target_date, len(predictions))
        # 
        # if y_true is None or len(y_true) != len(predictions):
        #     logger.warning(f"Ground truth data unavailable or mismatched for {target_date}")
        #     return None
        # 
        # y_pred = [p.binary_prediction for p in predictions]
        # y_prob = [p.probability for p in predictions]
        # threshold = predictions[0].threshold
        # 
        # metrics = {
        #     "brier_score": float(brier_score_loss(y_true, y_prob)),
        #     "f1_score": float(f1_score(y_true, y_pred, zero_division=0)),
        #     "f2_score": float(fbeta_score(y_true, y_pred, beta=2, zero_division=0)),
        #     "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        #     "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        #     "threshold": threshold,
        # }
        # 
        # cm = confusion_matrix(y_true, y_pred)
        # metrics["confusion_matrix"] = {
        #     "TN": int(cm[0, 0]),
        #     "FP": int(cm[0, 1]),
        #     "FN": int(cm[1, 0]),
        #     "TP": int(cm[1, 1]),
        # }
        # 
        # # Calculate calibration slope (simple linear regression)
        # if len(y_prob) > 1:
        #     try:
        #         from sklearn.linear_model import LogisticRegression
        #         lr = LogisticRegression()
        #         lr.fit(np.array(y_prob).reshape(-1, 1), y_true)
        #         metrics["calibration_slope"] = float(lr.coef_[0][0])
        #     except Exception as e:
        #         logger.warning(f"Failed to calculate calibration slope: {e}")
        #         metrics["calibration_slope"] = None
        # else:
        #     metrics["calibration_slope"] = None
        # 
        # logger.info(f"Calculated metrics for model {model_id}: F2={metrics['f2_score']:.4f}")
        # return metrics
        
        logger.info("Ground truth data not yet available - skipping metrics calculation")
        return None
    
    async def _fetch_ground_truth(
        self, 
        target_date: date, 
        expected_count: int
    ) -> Optional[List[int]]:
        """
        Fetch ground truth labels for the given date.
        
        Args:
            target_date: Date to fetch ground truth for
            expected_count: Expected number of labels
            
        Returns:
            List of binary labels (0/1) or None if unavailable
        """
        # TODO: Implement fetching from weather_data table or external API
        # This will depend on how actual rainfall data is stored
        # Example:
        # result = await self.db.execute(
        #     select(WeatherData.rainfall)
        #     .where(
        #         and_(
        #             WeatherData.timestamp >= target_date,
        #             WeatherData.timestamp < target_date + timedelta(days=1),
        #         )
        #     )
        #     .order_by(WeatherData.timestamp)
        # )
        # rainfall_data = result.scalars().all()
        # return [1 if r > 0 else 0 for r in rainfall_data]
        
        return None
