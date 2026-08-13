from sqlalchemy import Column, Integer, Date, DateTime, JSON, func
from ..database import Base


class Report(Base):
    """
    Daily rain prediction report model.

    Stores complete daily reports with predictions, metrics, and visualizations
    in structured JSON format for API access and historical analysis.

    JSON Schema for Report.content field:

        {
          "date": "2026-07-22",
          "models": [
            {
              "name": "baseline",
              "version": "1.0.0",
              "metrics": {
                "f2": 0.72,
                "precision": 0.65,
                "recall": 0.80,
                "accuracy": 0.75
              },
              "predictions": [
                {
                  "timestamp": "2026-07-22T00:00:00Z",
                  "rain_prob": 0.3,
                  "rain_pred": false,
                  "confidence": 0.85
                }
              ]
            }
          ],
          "weather_summary": {
            "avg_temp": 22.5,
            "avg_humidity": 65.0,
            "avg_pressure": 1013.2,
            "min_temp": 18.0,
            "max_temp": 28.0
          },
          "charts_data": {
            "predictions_timeline": [
              {"x": "2026-07-22T00:00:00Z", "y": 0.3, "model": "baseline"}
            ],
            "metrics_comparison": [
              {"model": "baseline", "f2": 0.72, "precision": 0.65}
            ]
          }
        }

    JSON Schema for Report.meta field:

        {
          "model_versions": {
            "baseline": "1.0.0",
            "ensemble": "2.1.0"
          },
          "data_coverage": 0.95,
          "generation_time": "2026-07-23T00:15:00Z",
          "data_sources": ["yandex", "openweather"],
          "notes": "Complete data for all models"
        }
    """
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    date = Column(Date, unique=True, nullable=False, index=True)
    content = Column(JSON, nullable=False)  # Full report structure (see JSON schema above)
    meta = Column(JSON, nullable=True)  # Summary: model versions, data coverage, etc.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
