import uuid
import enum
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Enum, Text, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, INET
from sqlalchemy.orm import relationship
from ..db.database import Base


class AuditAction(str, enum.Enum):
    LOGIN = "login"
    LOGOUT = "logout"
    QUERY = "query"
    DOCUMENT_UPLOAD = "document_upload"
    DOCUMENT_ACCESS = "document_access"
    DOCUMENT_DELETE = "document_delete"
    REINDEX = "reindex"
    USER_CREATE = "user_create"
    USER_UPDATE = "user_update"
    USER_DELETE = "user_delete"
    PERMISSION_CHANGE = "permission_change"
    EXPORT = "export"
    ADMIN_ACTION = "admin_action"


class AuditLog(Base):
    """HIPAA-compliant audit trail for all data access and system operations."""

    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(Enum(AuditAction), nullable=False, index=True)
    resource_type = Column(String(100))
    resource_id = Column(String(255))
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    request_path = Column(String(500))
    request_method = Column(String(10))
    status_code = Column(String(10))
    details = Column(JSON, default={})
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True)

    user = relationship("User", back_populates="audit_logs")

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} user={self.user_id} at={self.created_at}>"
