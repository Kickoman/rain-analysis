from sqlalchemy import Column, Integer, String, DateTime, func
from sqlalchemy.orm import relationship
from ..database import Base


class Sensor(Base):
    __tablename__ = "sensors"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    unit = Column(String, nullable=True)  # "°C", "%", "mm"
    sensor_type = Column(String, nullable=False, default="numeric")  # numeric, boolean, text
    description = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relations
    measurements = relationship("Measurement", back_populates="sensor", cascade="all, delete-orphan")
