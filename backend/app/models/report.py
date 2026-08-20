from sqlalchemy import Column, Integer, Date, DateTime, JSON, Text, func
from ..database import Base


class Report(Base):
    """
    Daily rain prediction report model.

    Stores daily reports migrated from markdown (and, in the future, generated
    directly by the API) in structured JSON for API access and history analysis.

    The ``content`` schema mirrors the sections that actually exist in the
    markdown reports produced by ``scripts_utils/daily_analysis.py``. It does
    **not** include ``predictions`` or ``weather_summary`` (avg_temp / avg_humidity
    / avg_pressure): those are not present in the legacy markdown and cannot be
    extracted from it. They will only appear in future API-generated reports
    (once data ingestion, issue #307, is complete), and the schema will then be
    extended with an optional ``predictions`` field.

    JSON Schema for Report.content field:

        {
          "date": "2026-08-13",
          "generated_at": "2026-08-13T05:04:03Z",
          "executive_summary": {
            "best_overall_f2": {"model": "pressure_primary", "window": "7d"},
            "key_findings": ["..."]
          },
          "data_context": {
            "ground_truth_source": "open-meteo",
            "coverage": {
              "home_assistant": 0.994,
              "open_meteo": 1.0,
              "yandex": 1.0,
              "meteostat": 1.0
            },
            "distribution": {"rain_hours": 9, "dry_hours": 161},
            "low_coverage_warning": false
          },
          "models": [
            {
              "name": "pressure_primary",
              "status": "📊",
              "metrics": {
                "7d": {"f1": 0.435, "precision": 0.357, "recall": 0.556}
              }
            }
          ],
          "multi_window_comparison": {
            "f2_scores": [
              {"model": "pressure_primary", "7d": null, "14d": 0.39, "28d": 0.39, "trend": "— not comparable"}
            ],
            "precision_by_window": [
              {"model": "pressure_primary", "7d": 0.357, "14d": 0.375, "28d": 0.375}
            ],
            "recall_by_window": [
              {"model": "pressure_primary", "7d": 0.556, "14d": 0.353, "28d": 0.353}
            ]
          },
          "rankings": {
            "f2": [
              {"rank": 1, "model": "pressure_primary", "f2": 0.208, "precision": 0.357, "recall": 0.556, "notes": ""}
            ],
            "f3": [],
            "precision": [
              {"rank": 1, "model": "pressure_primary", "precision": 0.357, "recall": 0.556, "f1": 0.435}
            ]
          },
          "temporal_metrics": [
            {"model": "pressure_primary", "f1": 0.947, "precision": 0.9, "recall": 1.0,
             "best_threshold": "55%", "window": "7d"}
          ],
          "precipitation_source_reliability": [
            {"source": "OM", "rain_hours": 9, "agreement": {"MS": 3, "YX": 1}}
          ]
        }

    Notes on the schema:

    - Metric values may be ``null`` (rendered as ``N/A`` in markdown) when a
      model has no labelled examples for a window — ``N/A`` is a value, not a
      parse error.
    - ``predictions`` / ``weather_summary`` / ``charts_data`` are intentionally
      absent for migrated reports; see above.

    JSON Schema for Report.meta field:

        {
          "source": "markdown_migration",
          "original_file": "reports/2026-08-13.md",
          "migrated_at": "2026-08-20T00:00:00Z",
          "model_versions": {"baseline": "1.0.0"}
        }

    ``meta`` holds a small provenance/summary. ``source_markdown`` keeps the raw
    markdown of migrated reports so the migration is reversible and re-runnable
    without the original files (the parser can be improved later and the history
    re-migrated without data loss).
    """
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    date = Column(Date, unique=True, nullable=False, index=True)
    content = Column(JSON, nullable=False)  # Full report structure (see JSON schema above)
    meta = Column(JSON, nullable=True)  # Summary: provenance, model versions, coverage, etc.
    source_markdown = Column(Text, nullable=True)  # Raw markdown of migrated reports (reversibility)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
