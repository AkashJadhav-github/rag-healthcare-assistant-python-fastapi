import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..config import settings
from ..db.database import Base


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class DocumentCategory(str, enum.Enum):
    CLINICAL_GUIDELINE = "clinical_guideline"
    RESEARCH_PAPER = "research_paper"
    HOSPITAL_POLICY = "hospital_policy"
    HL7_STANDARD = "hl7_standard"
    MEDICATION_DB = "medication_db"
    MEDICAL_GLOSSARY = "medical_glossary"
    OTHER = "other"


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(500), nullable=False)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)
    file_size = Column(Integer)
    category = Column(Enum(DocumentCategory), default=DocumentCategory.OTHER)
    source = Column(String(500))
    version = Column(String(50), default="1.0")
    status = Column(Enum(DocumentStatus), default=DocumentStatus.PENDING, nullable=False, index=True)
    chunk_count = Column(Integer, default=0)
    error_message = Column(Text)
    metadata = Column(JSON, default={})
    is_active = Column(Boolean, default=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    indexed_at = Column(DateTime(timezone=True))

    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Document {self.title} status={self.status}>"


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), index=True)
    embedding = Column(Vector(settings.VECTOR_DIMENSION))
    token_count = Column(Integer)
    page_number = Column(Integer)
    section = Column(String(500))
    metadata = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="chunks")

    def __repr__(self) -> str:
        return f"<DocumentChunk doc={self.document_id} idx={self.chunk_index}>"
