import hashlib
import os
import time
import uuid
from typing import List, Optional

import aiofiles
import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.rbac import Permission
from ...db.database import get_db
from ...models.audit import AuditAction, AuditLog
from ...models.document import Document, DocumentCategory, DocumentStatus
from ...models.query import QueryLog, QuerySource
from ...models.user import User
from ...services.cache import cache_service
from ...services.metrics import ingest_total, query_latency, query_total
from ..deps import get_client_ip, require_permission

logger = structlog.get_logger()
router = APIRouter()


# ─── Request / Response Schemas ─────────────────────────────────────────────


class AskRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=2000)
    session_id: Optional[str] = None
    max_sources: int = Field(default=5, ge=1, le=10)
    include_sources: bool = True
    stream: bool = False


class SourceCitation(BaseModel):
    document_title: str
    document_id: str
    chunk_content: str
    similarity_score: float
    rank: int
    page_number: Optional[int] = None
    section: Optional[str] = None


class AskResponse(BaseModel):
    query_id: str
    answer: str
    sources: List[SourceCitation] = []
    confidence_score: float
    latency_ms: int
    was_cached: bool
    model_used: str


class IngestResponse(BaseModel):
    document_id: str
    title: str
    status: str
    message: str


class QueryHistoryItem(BaseModel):
    query_id: str
    query_text: str
    response_text: Optional[str]
    confidence_score: Optional[float]
    latency_ms: Optional[int]
    was_cached: bool
    sources_count: int
    created_at: str


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/ask", response_model=AskResponse)
async def ask_question(
    request_body: AskRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.QUERY)),
    client_ip: str = Depends(get_client_ip),
):
    """Submit a query and receive a response with source citations."""
    start_time = time.time()

    sanitized_query = _sanitize_query(request_body.query)
    query_hash = hashlib.sha256(sanitized_query.encode()).hexdigest()

    cache_key = cache_service.make_query_key(sanitized_query, str(current_user.id))
    cached_result = await cache_service.get(cache_key)
    if cached_result:
        query_total.labels(status="success", cached="true").inc()
        cached_result["was_cached"] = True
        await _log_audit(
            db, current_user.id, AuditAction.QUERY, client_ip, {"query_hash": query_hash, "cached": True}
        )
        return AskResponse(**cached_result)

    try:
        from ....rag.pipeline import RAGPipeline

        pipeline = RAGPipeline()
        result = await pipeline.query(
            query=sanitized_query,
            max_sources=request_body.max_sources,
            user_id=str(current_user.id),
        )

        latency_ms = int((time.time() - start_time) * 1000)

        query_log = QueryLog(
            user_id=current_user.id,
            session_id=request_body.session_id or str(uuid.uuid4()),
            query_text=sanitized_query,
            query_hash=query_hash,
            response_text=result["answer"],
            confidence_score=result.get("confidence_score", 0.0),
            latency_ms=latency_ms,
            llm_model=result.get("model_used", settings.OPENAI_LLM_MODEL),
            retrieval_count=len(result.get("sources", [])),
            was_cached=False,
        )
        db.add(query_log)
        await db.flush()

        sources = []
        for idx, src in enumerate(result.get("sources", [])):
            qs = QuerySource(
                query_id=query_log.id,
                document_id=src.get("document_id"),
                chunk_id=src.get("chunk_id"),
                document_title=src.get("document_title", "Unknown"),
                chunk_content=src.get("chunk_content", ""),
                similarity_score=src.get("similarity_score", 0.0),
                rank=idx + 1,
            )
            db.add(qs)
            sources.append(
                SourceCitation(
                    document_title=src.get("document_title", "Unknown"),
                    document_id=str(src.get("document_id", "")),
                    chunk_content=src.get("chunk_content", ""),
                    similarity_score=src.get("similarity_score", 0.0),
                    rank=idx + 1,
                    page_number=src.get("page_number"),
                    section=src.get("section"),
                )
            )

        await db.commit()

        response = AskResponse(
            query_id=str(query_log.id),
            answer=result["answer"],
            sources=sources if request_body.include_sources else [],
            confidence_score=result.get("confidence_score", 0.0),
            latency_ms=latency_ms,
            was_cached=False,
            model_used=result.get("model_used", settings.OPENAI_LLM_MODEL),
        )

        await cache_service.set(cache_key, response.model_dump(), ttl=1800)
        query_total.labels(status="success", cached="false").inc()
        query_latency.observe(time.time() - start_time)

        await _log_audit(db, current_user.id, AuditAction.QUERY, client_ip, {"query_hash": query_hash})
        return response

    except Exception as e:
        logger.error("query_failed", error=str(e), user_id=str(current_user.id))
        query_total.labels(status="error", cached="false").inc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Query processing failed"
        )


@router.post("/ingest", response_model=IngestResponse)
async def ingest_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    category: DocumentCategory = Form(DocumentCategory.OTHER),
    source: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.INGEST)),
    client_ip: str = Depends(get_client_ip),
):
    """Upload a document for RAG indexing."""
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type .{ext} not supported. Allowed: {settings.ALLOWED_EXTENSIONS}",
        )

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.MAX_DOCUMENT_SIZE_MB:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.MAX_DOCUMENT_SIZE_MB}MB limit",
        )

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    doc_id = uuid.uuid4()
    save_path = os.path.join(settings.UPLOAD_DIR, f"{doc_id}.{ext}")
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(content)

    document = Document(
        id=doc_id,
        title=title or file.filename,
        filename=file.filename,
        file_type=ext,
        file_size=len(content),
        category=category,
        source=source,
        status=DocumentStatus.PENDING,
        uploaded_by=current_user.id,
    )
    db.add(document)
    await db.commit()

    background_tasks.add_task(_process_document, str(doc_id), save_path, ext)

    ingest_total.labels(status="accepted", file_type=ext).inc()
    await _log_audit(
        db,
        current_user.id,
        AuditAction.DOCUMENT_UPLOAD,
        client_ip,
        {"document_id": str(doc_id), "filename": file.filename},
    )

    return IngestResponse(
        document_id=str(doc_id),
        title=title or file.filename,
        status="pending",
        message="Document queued for processing",
    )


@router.get("/history", response_model=List[QueryHistoryItem])
async def get_query_history(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.VIEW_HISTORY)),
):
    """Retrieve query history for the current user."""
    offset = (page - 1) * page_size
    result = await db.execute(
        select(QueryLog)
        .where(QueryLog.user_id == current_user.id)
        .order_by(desc(QueryLog.created_at))
        .offset(offset)
        .limit(page_size)
    )
    logs = result.scalars().all()

    history = []
    for log in logs:
        sources_result = await db.execute(select(QuerySource).where(QuerySource.query_id == log.id))
        sources_count = len(sources_result.scalars().all())
        history.append(
            QueryHistoryItem(
                query_id=str(log.id),
                query_text=log.query_text,
                response_text=log.response_text,
                confidence_score=log.confidence_score,
                latency_ms=log.latency_ms,
                was_cached=log.was_cached or False,
                sources_count=sources_count,
                created_at=log.created_at.isoformat() if log.created_at else "",
            )
        )
    return history


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _sanitize_query(query: str) -> str:
    """Strip prompt injection attempts and normalize whitespace."""
    import re

    query = re.sub(r"(ignore previous instructions|system prompt|<[^>]+>)", "", query, flags=re.IGNORECASE)
    query = " ".join(query.split())
    return query[:2000]


async def _process_document(doc_id: str, file_path: str, file_type: str) -> None:
    """Background task: chunk, embed, and index the document."""
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../"))
    from app.db.database import AsyncSessionLocal
    from app.models.document import Document, DocumentStatus
    from rag.ingestion import DocumentIngestionService

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(Document).where(Document.id == doc_id))
            doc = result.scalar_one_or_none()
            if not doc:
                return
            doc.status = DocumentStatus.PROCESSING
            await db.commit()

            ingestion = DocumentIngestionService()
            chunk_count = await ingestion.ingest(
                doc_id=doc_id, file_path=file_path, file_type=file_type, db=db
            )

            doc.status = DocumentStatus.INDEXED
            doc.chunk_count = chunk_count
            from datetime import datetime

            doc.indexed_at = datetime.utcnow()
            await db.commit()
        except Exception as e:
            logger.error("document_processing_failed", doc_id=doc_id, error=str(e))
            result = await db.execute(select(Document).where(Document.id == doc_id))
            doc = result.scalar_one_or_none()
            if doc:
                doc.status = DocumentStatus.FAILED
                doc.error_message = str(e)
                await db.commit()
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)


async def _log_audit(db: AsyncSession, user_id, action: AuditAction, ip: str, details: dict) -> None:
    try:
        log = AuditLog(user_id=user_id, action=action, ip_address=ip, details=details)
        db.add(log)
        await db.commit()
    except Exception as e:
        logger.warning("audit_log_failed", error=str(e))
