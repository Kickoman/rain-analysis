"""
Metrics calculator for model performance evaluation.

Compares a model's stored predictions for a day with ground truth read
back from the measurements table. Ground truth is the sensor named by
GROUND_TRUTH_SENSOR (Open-Meteo precipitation pushed by the pipeline —
the backend itself makes no outbound HTTP requests); an hour counts as
rain when precipitation > 0 mm.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import logging

import pandas as pd

from ..models import Measurement, Sensor
from ..models.ml import Prediction

logger = logging.getLogger(__name__)

GROUND_TRUTH_SENSOR = "openmeteo.precipitation"

# Fewer matched prediction/truth hours than this and the day's metrics are
# statistical noise — skip instead of storing misleading numbers.
MIN_MATCHED_HOURS = 6


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

        Returns:
            Dictionary with metrics or None if insufficient data
        """
        import numpy as np
        from sklearn.metrics import (
            brier_score_loss,
            f1_score,
            fbeta_score,
            precision_score,
            recall_score,
            confusion_matrix,
        )

        day_start = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        result = await self.db.execute(
            select(Prediction)
            .where(
                and_(
                    Prediction.model_id == model_id,
                    Prediction.timestamp >= day_start,
                    Prediction.timestamp < day_end,
                )
            )
            .order_by(Prediction.timestamp)
        )
        predictions = result.scalars().all()

        if not predictions:
            logger.warning(f"No predictions found for model {model_id} on {target_date}")
            return None

        truth_by_hour = await self._fetch_ground_truth(target_date)
        if truth_by_hour is None:
            logger.info(f"Ground truth unavailable for {target_date} - skipping metrics")
            return None

        # Align on the hour: prediction at HH:MM scores against truth for HH
        y_true, y_pred, y_prob = [], [], []
        for p in predictions:
            ts = p.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            hour = ts.replace(minute=0, second=0, microsecond=0)
            truth = truth_by_hour.get(hour)
            if truth is None:
                continue
            y_true.append(truth)
            y_pred.append(int(p.binary_prediction))
            y_prob.append(float(p.probability))

        if len(y_true) < MIN_MATCHED_HOURS:
            logger.warning(
                f"Only {len(y_true)} prediction/truth hours matched for model "
                f"{model_id} on {target_date} (need {MIN_MATCHED_HOURS}) - skipping"
            )
            return None

        threshold = predictions[0].threshold

        metrics = {
            "brier_score": float(brier_score_loss(y_true, y_prob)),
            "f1_score": float(f1_score(y_true, y_pred, zero_division=0)),
            "f2_score": float(fbeta_score(y_true, y_pred, beta=2, zero_division=0)),
            "precision": float(precision_score(y_true, y_pred, zero_division=0)),
            "recall": float(recall_score(y_true, y_pred, zero_division=0)),
            "threshold": threshold,
        }

        cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
        metrics["confusion_matrix"] = {
            "TN": int(cm[0, 0]),
            "FP": int(cm[0, 1]),
            "FN": int(cm[1, 0]),
            "TP": int(cm[1, 1]),
        }

        # Calibration slope via single-feature logistic fit; undefined when
        # the day is all-rain or all-dry
        if len(set(y_true)) > 1:
            try:
                from sklearn.linear_model import LogisticRegression
                lr = LogisticRegression()
                lr.fit(np.array(y_prob).reshape(-1, 1), y_true)
                metrics["calibration_slope"] = float(lr.coef_[0][0])
            except Exception as e:
                logger.warning(f"Failed to calculate calibration slope: {e}")
                metrics["calibration_slope"] = None
        else:
            metrics["calibration_slope"] = None

        logger.info(
            f"Calculated metrics for model {model_id} on {target_date} "
            f"({len(y_true)} hours): F2={metrics['f2_score']:.4f}"
        )
        return metrics

    async def _fetch_ground_truth(self, target_date: date) -> Optional[Dict[datetime, int]]:
        """
        Rain/no-rain per UTC hour of the target date, from stored
        GROUND_TRUTH_SENSOR measurements. None when the sensor is absent
        or has no rows for the day.
        """
        sensor = (
            await self.db.execute(
                select(Sensor).where(Sensor.name == GROUND_TRUTH_SENSOR)
            )
        ).scalar_one_or_none()
        if sensor is None:
            return None

        day_start = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        result = await self.db.execute(
            select(Measurement)
            .where(
                Measurement.sensor_id == sensor.id,
                Measurement.timestamp >= day_start,
                Measurement.timestamp < day_end,
            )
            .order_by(Measurement.timestamp)
        )
        rows = result.scalars().all()
        if not rows:
            return None

        truth: Dict[datetime, int] = {}
        for m in rows:
            value = pd.to_numeric(m.value, errors="coerce")
            if pd.isna(value):
                continue
            ts = m.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            hour = ts.replace(minute=0, second=0, microsecond=0)
            # Multiple rows within an hour: any rain marks the hour as rain
            truth[hour] = max(truth.get(hour, 0), int(float(value) > 0))
        return truth or None
