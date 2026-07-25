from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text
from sqlalchemy.orm import relationship
from ..database import Base


class ModelMetric(Base):
    __tablename__ = "model_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("models.id", ondelete="CASCADE"), nullable=False)
    metric_name = Column(String, nullable=False)  # f2, precision, recall, ...
    metric_value = Column(Float, nullable=False)
    evaluation_date = Column(DateTime(timezone=True), nullable=False)
    dataset_info = Column(Text, nullable=True)  # JSON с инфо о датасете
    
    # Relations
    model = relationship("MLModel", back_populates="metrics")
