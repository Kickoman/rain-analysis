"""Admin Audit Log model for tracking administrative actions."""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import relationship
from backend.app.models.base import Base


class AdminAuditLog(Base):
    """Audit log for administrative actions on API keys."""

    __tablename__ = "admin_audit_log"

    id = Column(Integer, primary_key=True, index=True)
    admin_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False, index=True)
    action = Column(String(50), nullable=False)  # create_key, revoke_key, update_limits, etc.
    target_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=True, index=True)
    details = Column(JSON, nullable=True)  # Additional context
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    # Relationships
    admin_key = relationship("APIKey", foreign_keys=[admin_key_id])
    target_key = relationship("APIKey", foreign_keys=[target_key_id], back_populates="audit_logs")
