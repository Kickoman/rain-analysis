from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text, Index
from sqlalchemy.orm import relationship
from ..database import Base


class Prediction(Base):
    __tablename__ = "predictions"
    
    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("models.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    prediction = Column(Text, nullable=False)  # JSON prediction result
    confidence = Column(Float, nullable=True)
    input_data = Column(Text, nullable=True)  # JSON для воспроизводимости
    
    # Relations
    model = relationship("MLModel", back_populates="predictions")
    
    # Indexes
    __table_args__ = (
        Index("idx_predictions_timestamp", "timestamp"),
        Index("idx_predictions_model_id", "model_id"),
    )
