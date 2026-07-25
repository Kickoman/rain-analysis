from sqlalchemy import Column, Integer, String, DateTime, Text, func
from sqlalchemy.orm import relationship
from ..database import Base


class MLModel(Base):
    __tablename__ = "models"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    version = Column(String, nullable=False)
    config = Column(Text, nullable=True)  # JSON config
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relations
    predictions = relationship("Prediction", back_populates="model", cascade="all, delete-orphan")
    metrics = relationship("ModelMetric", back_populates="model", cascade="all, delete-orphan")
