import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..db.database import Base


class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id = Column(String(100), index=True)
    query_text = Column(Text, nullable=False)
    query_hash = Column(String(64), index=True)
    response_text = Column(Text)
    enhanced_query = Column(Text)
    confidence_score = Column(Float)
    latency_ms = Column(Integer)
    llm_model = Column(String(100))
    embedding_model = Column(String(100))
    retrieval_count = Column(Integer, default=0)
    token_count_prompt = Column(Integer)
    token_count_completion = Column(Integer)
    was_cached = Column(Boolean, default=False)
    error = Column(Text)
    extra_metadata = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True)

    user = relationship("User", back_populates="queries")
    sources = relationship("QuerySource", back_populates="query", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<QueryLog {self.id} user={self.user_id}>"


class QuerySource(Base):
    __tablename__ = "query_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_id = Column(
        UUID(as_uuid=True), ForeignKey("query_logs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    chunk_id = Column(
        UUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )
    document_title = Column(String(500))
    chunk_content = Column(Text)
    similarity_score = Column(Float)
    rank = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    query = relationship("QueryLog", back_populates="sources")

    def __repr__(self) -> str:
        return f"<QuerySource query={self.query_id} rank={self.rank}>"
