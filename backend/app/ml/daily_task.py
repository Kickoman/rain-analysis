"""
Daily ML task for automated predictions and metrics calculation.

Runs daily at 00:00 UTC to:
1. Fetch sensor measurements for yesterday from the measurements table
2. Generate predictions for all active models
3. Calculate performance metrics (when ground truth is available)

Feature sourcing contract: each MLModel.config carries
  - "sensor_map": {feature_name: sensor_name} — which stored sensor feeds
    which model feature (e.g. {"spread": "sensor.outside_dew_point_spread"})
  - "features": ordered feature list the estimator expects
Measurements are pulled for the union of mapped sensors, resampled to an
hourly grid, and forward-filled across gaps of up to 2 hours.
"""

from datetime import datetime, timedelta, date, timezone
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from ..database import AsyncSessionLocal
from ..models import Measurement, Sensor
from ..models.ml import MLModel, ModelMetric
from .prediction_service import PredictionService
from .metrics_calculator import MetricsCalculator

logger = logging.getLogger(__name__)

# Gaps longer than this are left as NaN and the rows dropped per-model
FFILL_LIMIT_HOURS = 2


class DailyMLTask:
    """Daily task to generate predictions and calculate metrics."""

    async def run(self, db: AsyncSession = None, target_date: date = None):
        """
        Main task execution.

        Args:
            db: Optional database session (for testing). If None, creates new session.
            target_date: Day to process (default: yesterday UTC).
        """
        try:
            logger.info("=" * 60)
            logger.info("Starting daily ML task")
            logger.info("=" * 60)

            if db is not None:
                await self._run_impl(db, target_date)
            else:
                async with AsyncSessionLocal() as db:
                    await self._run_impl(db, target_date)

        except Exception as e:
            logger.error(f"Daily ML task failed: {e}", exc_info=True)
            raise

    async def _run_impl(self, db: AsyncSession, target_date: date = None):
        """Internal implementation of run logic."""
        if target_date is None:
            target_date = datetime.now(timezone.utc).date() - timedelta(days=1)
        logger.info(f"Target date: {target_date}")

        service = PredictionService(db)
        models = await service.get_active_models()
        if not models:
            logger.warning("No active models found - skipping task")
            return

        # Union of sensors any active model needs
        sensor_names = sorted({
            sensor_name
            for model in models
            for sensor_name in ((model.config or {}).get("sensor_map") or {}).values()
        })
        if not sensor_names:
            logger.warning("No active model declares a sensor_map - skipping task")
            return

        wide_df = await self._fetch_weather_data(db, target_date, sensor_names)
        if wide_df.empty:
            logger.warning(f"No weather data available for {target_date} - skipping task")
            return

        logger.info(f"Fetched {len(wide_df)} hourly rows for {target_date} "
                    f"({len(wide_df.columns)} sensors)")
        logger.info(f"Processing {len(models)} active models")

        for model in models:
            try:
                await self._process_model(db, model, wide_df, target_date)
            except Exception as e:
                logger.error(
                    f"Error processing model {model.name} (ID: {model.id}): {e}",
                    exc_info=True
                )
                continue

        logger.info("=" * 60)
        logger.info("Daily ML task completed")
        logger.info("=" * 60)

    async def _fetch_weather_data(
        self,
        db: AsyncSession,
        target_date: date,
        sensor_names: list[str],
    ) -> pd.DataFrame:
        """
        Load the day's measurements for the given sensors as an hourly frame.

        Returns a DataFrame indexed by UTC hour with one column per sensor
        name. Values failing numeric decoding become NaN; gaps of up to
        FFILL_LIMIT_HOURS hours are forward-filled.
        """
        day_start = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        result = await db.execute(select(Sensor).where(Sensor.name.in_(sensor_names)))
        sensors = {s.id: s.name for s in result.scalars()}
        if not sensors:
            return pd.DataFrame()

        result = await db.execute(
            select(Measurement)
            .where(
                Measurement.sensor_id.in_(list(sensors)),
                Measurement.timestamp >= day_start,
                Measurement.timestamp < day_end,
            )
            .order_by(Measurement.timestamp)
        )
        rows = result.scalars().all()
        if not rows:
            return pd.DataFrame()

        records = []
        for m in rows:
            ts = m.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            records.append({
                "sensor": sensors[m.sensor_id],
                "timestamp": ts,
                "value": pd.to_numeric(m.value, errors="coerce"),
            })

        frame = pd.DataFrame(records)
        wide = (
            frame.pivot_table(index="timestamp", columns="sensor", values="value", aggfunc="mean")
            .resample("1h")
            .mean()
            .ffill(limit=FFILL_LIMIT_HOURS)
        )
        wide.index.name = None
        wide.columns.name = None
        return wide

    def _build_features(self, model: MLModel, wide_df: pd.DataFrame) -> pd.DataFrame:
        """Map the sensor-named frame onto the model's feature names."""
        config = model.config or {}
        sensor_map = config.get("sensor_map") or {}

        features = pd.DataFrame(index=wide_df.index)
        missing_sensors = []
        for feature_name, sensor_name in sensor_map.items():
            if sensor_name in wide_df.columns:
                features[feature_name] = wide_df[sensor_name]
            else:
                missing_sensors.append(sensor_name)
        if missing_sensors:
            logger.warning(
                f"Model {model.name}: no data for sensors {missing_sensors}"
            )

        # Rows where any mapped feature is missing cannot be scored
        features = features.dropna()
        return features

    async def _process_model(
        self,
        db: AsyncSession,
        model: MLModel,
        wide_df: pd.DataFrame,
        target_date: date
    ):
        """
        Generate predictions and calculate metrics for one model.
        """
        logger.info(f"Processing model: {model.name} (ID: {model.id})")

        features_df = self._build_features(model, wide_df)
        if features_df.empty:
            logger.warning(f"Model {model.name}: no usable feature rows for {target_date}")
            return

        service = PredictionService(db)
        timestamps = [ts.to_pydatetime() for ts in features_df.index]

        try:
            stored = await service.predict_and_store(model.id, features_df, timestamps)
            logger.info(f"Stored {stored} predictions for {model.name}")
        except Exception as e:
            logger.error(f"Failed to generate predictions for {model.name}: {e}")
            raise

        # Calculate metrics if ground truth is available
        calculator = MetricsCalculator(db)
        metrics = await calculator.calculate_daily_metrics(model.id, target_date)

        if metrics:
            # Upsert: re-running a day refreshes the metric row
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            row = {
                "model_id": model.id,
                "date": target_date,
                "brier_score": metrics.get("brier_score"),
                "f1_score": metrics.get("f1_score"),
                "f2_score": metrics.get("f2_score"),
                "precision_score": metrics.get("precision"),
                "recall": metrics.get("recall"),
                "calibration_slope": metrics.get("calibration_slope"),
                "threshold": metrics.get("threshold"),
                "confusion_matrix": metrics.get("confusion_matrix"),
            }
            stmt = sqlite_insert(ModelMetric).values(**row)
            stmt = stmt.on_conflict_do_update(
                index_elements=["model_id", "date"],
                set_={k: v for k, v in row.items() if k not in ("model_id", "date")},
            )
            await db.execute(stmt)
            await db.commit()

            f2_str = f"{metrics['f2_score']:.4f}" if metrics.get('f2_score') is not None else "N/A"
            brier_str = f"{metrics['brier_score']:.4f}" if metrics.get('brier_score') is not None else "N/A"
            logger.info(f"Metrics saved for {model.name}: F2={f2_str}, Brier={brier_str}")
        else:
            logger.info(f"No metrics calculated for {model.name} (ground truth unavailable)")


# Singleton instance used by the scheduler and the admin trigger
_daily_task = DailyMLTask()
