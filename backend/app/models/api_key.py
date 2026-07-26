"""API Key model for authentication and authorization."""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, func
from sqlalchemy.orm import relationship
from ..database import Base


class APIKey(Base):
    """API Key model for managing access to the API."""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key_hash = Column(String(128), unique=True, nullable=False, index=True)
    key_prefix = Column(String(20), nullable=False, index=True)  # ra_live_abc12345 or ra_test_xyz67890
    owner = Column(String(100), nullable=True)
    description = Column(String(500), nullable=True)
    scope = Column(String(20), nullable=False, default="read")  # read, write, admin

    # Rate limits
    rate_limit_rpm = Column(Integer, nullable=True)  # requests per minute
    rate_limit_rph = Column(Integer, nullable=True)  # requests per hour
    rate_limit_rpd = Column(Integer, nullable=True)  # requests per day

    # Status
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    request_logs = relationship("APIRequestLog", back_populates="api_key")
    audit_logs = relationship("AdminAuditLog", foreign_keys="AdminAuditLog.target_key_id", back_populates="target_key")
