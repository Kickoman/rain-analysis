from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Index, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from ..database import Base


class Measurement(Base):
    __tablename__ = "measurements"

    id = Column(Integer, primary_key=True, index=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    value = Column(Text, nullable=False)  # text keeps the EAV table type-agnostic
    source = Column(String, default="manual")  # ha, manual, api, ...

    # Relations
    sensor = relationship("Sensor", back_populates="measurements")

    __table_args__ = (
        Index("idx_measurements_timestamp", "timestamp"),
        Index("idx_measurements_sensor_id", "sensor_id"),
        Index("idx_measurements_sensor_timestamp", "sensor_id", "timestamp"),
        UniqueConstraint("sensor_id", "timestamp", name="uq_measurement_sensor_ts"),
    )
