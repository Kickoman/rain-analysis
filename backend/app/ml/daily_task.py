"""
Daily ML task for automated predictions and metrics calculation.

Runs daily at 00:00 UTC to:
1. Fetch weather data for yesterday
2. Generate predictions for all active models
3. Calculate performance metrics (when ground truth available)

NOTE: This is a scaffolding implementation. Core functionality (_fetch_weather_data 
and calculate_daily_metrics) are not yet implemented and return empty/None results.
Issue #307 should remain open until full implementation is complete.
"""

from datetime import datetime, timedelta, date, timezone
import pandas as pd
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from ..database import AsyncSessionLocal
from ..models.ml import MLModel, Prediction, ModelMetric
from .prediction_service import PredictionService
from .metrics_calculator import MetricsCalculator

logger = logging.getLogger(__name__)


class DailyMLTask:
    """Daily task to generate predictions and calculate metrics."""
    
    async def run(self, db: AsyncSession = None):
        """
        Main task execution.
        
        Fetches weather data for yesterday, generates predictions for all active models,
        and calculates metrics if ground truth is available.
        
        Args:
            db: Optional database session (for testing). If None, creates new session.
        """
        try:
            logger.info("=" * 60)
            logger.info("Starting daily ML task")
            logger.info("=" * 60)
            
            # Use provided session or create new one
            if db is not None:
                await self._run_impl(db)
            else:
                async with AsyncSessionLocal() as db:
                    await self._run_impl(db)
                    
        except Exception as e:
            logger.error(f"Daily ML task failed: {e}", exc_info=True)
            raise
    
    async def _run_impl(self, db: AsyncSession):
        """Internal implementation of run logic."""
        # 1. Determine target date (yesterday)
        yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1))
        logger.info(f"Target date: {yesterday}")
        
        # 2. Fetch weather data for yesterday
        features_df = await self._fetch_weather_data(db, yesterday)
        
        if features_df.empty:
            logger.warning(f"No weather data available for {yesterday} - skipping task")
            return
        
        logger.info(f"Fetched {len(features_df)} weather records for {yesterday}")
        
        # 3. Get active models
        service = PredictionService(db)
        models = await service.get_active_models()
        
        if not models:
            logger.warning("No active models found - skipping task")
            return
        
        logger.info(f"Processing {len(models)} active models")
        
        # 4. Generate predictions for each model
        for model in models:
            try:
                await self._process_model(db, model, features_df, yesterday)
            except Exception as e:
                logger.error(
                    f"Error processing model {model.name} (ID: {model.id}): {e}", 
                    exc_info=True
                )
                continue
        
        logger.info("=" * 60)
        logger.info("Daily ML task completed successfully")
        logger.info("=" * 60)
    
    async def _fetch_weather_data(
        self, 
        db: AsyncSession, 
        target_date: date
    ) -> pd.DataFrame:
        """
        Fetch weather data from database or external API.
        
        Args:
            db: Database session
            target_date: Date to fetch data for
            
        Returns:
            DataFrame with weather features
        """
        # TODO: Implement data fetching from weather_data table or external API
        # This depends on how weather data is stored in the system
        # 
        # Example structure:
        # result = await db.execute(
        #     select(WeatherData)
        #     .where(
        #         and_(
        #             WeatherData.timestamp >= target_date,
        #             WeatherData.timestamp < target_date + timedelta(days=1),
        #         )
        #     )
        #     .order_by(WeatherData.timestamp)
        # )
        # records = result.scalars().all()
        # 
        # if not records:
        #     return pd.DataFrame()
        # 
        # # Convert to DataFrame with required features
        # data = []
        # for record in records:
        #     data.append({
        #         'temperature': record.temperature,
        #         'humidity': record.humidity,
        #         'pressure': record.pressure,
        #         'wind_speed': record.wind_speed,
        #         # ... other features
        #     })
        # 
        # return pd.DataFrame(data)
        
        logger.warning("Weather data fetching not yet implemented - returning empty DataFrame")
        return pd.DataFrame()
    
    async def _process_model(
        self, 
        db: AsyncSession, 
        model: MLModel, 
        features_df: pd.DataFrame, 
        target_date: date
    ):
        """
        Generate predictions and calculate metrics for one model.
        
        Args:
            db: Database session
            model: Model to process
            features_df: Weather features DataFrame
            target_date: Date being processed
        """
        logger.info(f"Processing model: {model.name} (ID: {model.id})")
        
        service = PredictionService(db)
        
        # Generate timestamps for predictions
        # Use actual timestamps from features_df if available, otherwise generate hourly
        if 'timestamp' in features_df.columns:
            timestamps = pd.to_datetime(features_df['timestamp']).tolist()
        else:
            start_datetime = datetime.combine(target_date, datetime.min.time())
            timestamps = [
                start_datetime + timedelta(hours=i) 
                for i in range(len(features_df))
            ]
        
        # Generate and store predictions
        try:
            stored = await service.predict_and_store(
                model.id, 
                features_df, 
                timestamps
            )
            logger.info(f"Generated {stored} predictions for {model.name}")
        except Exception as e:
            logger.error(f"Failed to generate predictions for {model.name}: {e}")
            raise
        
        # Calculate metrics if ground truth is available
        calculator = MetricsCalculator(db)
        metrics = await calculator.calculate_daily_metrics(model.id, target_date)
        
        if metrics:
            # Store metrics
            metric_record = ModelMetric(
                model_id=model.id,
                date=target_date,
                brier_score=metrics.get("brier_score"),
                f1_score=metrics.get("f1_score"),
                f2_score=metrics.get("f2_score"),
                precision_score=metrics.get("precision"),
                recall=metrics.get("recall"),
                calibration_slope=metrics.get("calibration_slope"),
                threshold=metrics.get("threshold"),
                confusion_matrix=metrics.get("confusion_matrix"),
            )
            db.add(metric_record)
            await db.commit()
            
            # Format metrics safely - check for None/numeric before formatting
            f2_str = f"{metrics['f2_score']:.4f}" if metrics.get('f2_score') is not None else "N/A"
            brier_str = f"{metrics['brier_score']:.4f}" if metrics.get('brier_score') is not None else "N/A"
            
            logger.info(
                f"Metrics saved for {model.name}: "
                f"F2={f2_str}, Brier={brier_str}"
            )
        else:
            logger.info(f"No metrics calculated for {model.name} (ground truth unavailable)")


# Singleton instance
_daily_task = DailyMLTask()


def run_daily_task():
    """
    Synchronous wrapper for scheduler.
    
    APScheduler's BackgroundScheduler requires a synchronous callable.
    This wrapper uses asyncio.run() to execute the async task.
    
    WARNING: This creates a new event loop for each execution. If using aiosqlite
    connection pooling, ensure the engine uses NullPool or is recreated within
    the task to avoid "attached to a different loop" errors. For production use,
    consider AsyncIOScheduler with the main event loop instead.
    """
    try:
        asyncio.run(_daily_task.run())
    except Exception as e:
        logger.error(f"Daily task wrapper failed: {e}", exc_info=True)
        raise
