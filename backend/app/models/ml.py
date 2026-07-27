from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Date, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base


class MLModel(Base):
    """ML model registry"""
    __tablename__ = "models"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    version = Column(String(20))
    description = Column(String(500))
    config = Column(JSON)  # {"features": [...], "hyperparameters": {...}, "file_path": "..."}
    active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    predictions = relationship("Prediction", back_populates="model", cascade="all, delete-orphan")
    metrics = relationship("ModelMetric", back_populates="model", cascade="all, delete-orphan")


class Prediction(Base):
    """Model predictions storage"""
    __tablename__ = "predictions"
    
    id = Column(Integer, primary_key=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    probability = Column(Float, nullable=False)
    threshold = Column(Float)
    binary_prediction = Column(Boolean)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    model = relationship("MLModel", back_populates="predictions")
    
    __table_args__ = (
        UniqueConstraint("model_id", "timestamp", name="uq_model_timestamp"),
    )


class ModelMetric(Base):
    """Daily model performance metrics"""
    __tablename__ = "model_metrics"
    
    id = Column(Integer, primary_key=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    brier_score = Column(Float)
    f1_score = Column(Float)
    f2_score = Column(Float)
    precision_score = Column(Float)
    recall = Column(Float)
    calibration_slope = Column(Float)
    threshold = Column(Float)
    confusion_matrix = Column(JSON)  # {"TP": 10, "FP": 2, "FN": 1, "TN": 50}
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    model = relationship("MLModel", back_populates="metrics")
    
    __table_args__ = (
        UniqueConstraint("model_id", "date", name="uq_model_date"),
    )
