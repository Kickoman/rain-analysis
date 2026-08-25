from sqlalchemy import Column, Integer, Date, DateTime, JSON, func

from ..database import Base


class Report(Base):
    """A daily analysis report pushed by the pipeline (variant B, #402).

    `content` holds the structured report (see schemas/report.py);
    `meta` holds provenance — including `source_markdown` for migrated
    reports, so the migration is reversible (#232).
    """

    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    report_date = Column(Date, nullable=False, unique=True, index=True)
    content = Column(JSON, nullable=False)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)
