import hashlib
import json
import os
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

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
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.rbac import Permission
from ...db.database import get_db
from ...middleware.rate_limit import limiter
from ...models.audit import AuditAction, AuditLog
from ...models.document import Document, DocumentCategory, DocumentChunk, DocumentStatus
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


class DeleteDocumentResponse(BaseModel):
    message: str
    document_id: str


class ReuploadDocumentResponse(BaseModel):
    message: str
    document_id: str
    version: int


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
@limiter.limit("60/minute")
async def ask_question(
    request: Request,
    request_body: AskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.QUERY)),
    client_ip: str = Depends(get_client_ip),
) -> Union[StreamingResponse, AskResponse]:
    """Submit a query and receive a response with source citations."""
    start_time = time.time()

    sanitized_query = _sanitize_query(request_body.query)
    query_hash = hashlib.sha256(sanitized_query.encode()).hexdigest()

    # ── Feature 2: build session conversation history ─────────────────────────
    conversation_history: List[dict] = []
    if request_body.session_id:
        history_result = await db.execute(
            select(QueryLog)
            .where(QueryLog.session_id == request_body.session_id)
            .order_by(desc(QueryLog.created_at))
            .limit(3)
        )
        recent_logs = history_result.scalars().all()
        # Reverse so the list is oldest-first
        conversation_history = [
            {"query": log.query_text, "answer": log.response_text}
            for log in reversed(recent_logs)
        ]

    # ── Cache check ───────────────────────────────────────────────────────────
    cache_key = cache_service.make_query_key(sanitized_query, str(current_user.id))
    cached_result = await cache_service.get(cache_key)

    # ── Feature 3: streaming path ─────────────────────────────────────────────
    if request_body.stream:

        async def event_generator() -> AsyncGenerator[str, None]:  # pragma: no cover
            if cached_result:
                query_total.labels(status="success", cached="true").inc()
                await _log_audit(
                    db,
                    current_user.id,
                    AuditAction.QUERY,
                    client_ip,
                    {"query_hash": query_hash, "cached": True, "stream": True},
                )
                # Stream the cached answer as a single chunk then done
                cached_answer = cached_result.get("answer", "")
                yield f"data: {json.dumps({'chunk': cached_answer, 'done': False})}\n\n"
                yield (
                    f"data: {json.dumps({'done': True, 'query_id': cached_result.get('query_id', ''), 'sources': cached_result.get('sources', []), 'confidence_score': cached_result.get('confidence_score', 0.0)})}\n\n"
                )
                return

            try:
                from rag.pipeline import RAGPipeline

                pipeline = RAGPipeline()

                final_meta: Dict[str, Any] = {}
                accumulated_answer: List[str] = []

                async for chunk_dict in pipeline.query_stream(
                    query=sanitized_query,
                    max_sources=request_body.max_sources,
                    user_id=str(current_user.id),
                    conversation_history=conversation_history or None,
                ):
                    if chunk_dict.get("done"):
                        final_meta = chunk_dict
                    else:
                        accumulated_answer.append(chunk_dict["chunk"])
                        yield f"data: {json.dumps({'chunk': chunk_dict['chunk'], 'done': False})}\n\n"

                # Persist the query log after streaming completes
                latency_ms = int((time.time() - start_time) * 1000)
                full_answer = "".join(accumulated_answer)
                source_dicts = final_meta.get("sources", [])
                confidence = final_meta.get("confidence_score", 0.0)

                query_log = QueryLog(
                    user_id=current_user.id,
                    session_id=request_body.session_id or str(uuid.uuid4()),
                    query_text=sanitized_query,
                    query_hash=query_hash,
                    response_text=full_answer,
                    confidence_score=confidence,
                    latency_ms=latency_ms,
                    llm_model=settings.OPENAI_LLM_MODEL,
                    retrieval_count=len(source_dicts),
                    was_cached=False,
                )
                db.add(query_log)
                await db.flush()

                sources_out = []
                for idx, src in enumerate(source_dicts):
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
                    sources_out.append(
                        {
                            "document_title": src.get("document_title", "Unknown"),
                            "document_id": str(src.get("document_id", "")),
                            "chunk_content": src.get("chunk_content", ""),
                            "similarity_score": src.get("similarity_score", 0.0),
                            "rank": idx + 1,
                            "page_number": src.get("page_number"),
                            "section": src.get("section"),
                        }
                    )

                await db.commit()

                query_total.labels(status="success", cached="false").inc()
                query_latency.observe(time.time() - start_time)
                await _log_audit(
                    db,
                    current_user.id,
                    AuditAction.QUERY,
                    client_ip,
                    {"query_hash": query_hash, "stream": True},
                )

                final_sources = sources_out if request_body.include_sources else []
                yield (
                    f"data: {json.dumps({'done': True, 'query_id': str(query_log.id), 'sources': final_sources, 'confidence_score': confidence})}\n\n"
                )

            except Exception as e:
                logger.error(
                    "stream_query_failed", error=str(e), user_id=str(current_user.id)
                )
                query_total.labels(status="error", cached="false").inc()
                yield f"data: {json.dumps({'error': 'Query processing failed', 'done': True})}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # ── Non-streaming path (original behavior) ────────────────────────────────
    if cached_result:
        query_total.labels(status="success", cached="true").inc()
        cached_result["was_cached"] = True
        await _log_audit(
            db,
            current_user.id,
            AuditAction.QUERY,
            client_ip,
            {"query_hash": query_hash, "cached": True},
        )
        return AskResponse(**cached_result)

    try:
        from rag.pipeline import RAGPipeline

        pipeline = RAGPipeline()
        result = await pipeline.query(
            query=sanitized_query,
            max_sources=request_body.max_sources,
            user_id=str(current_user.id),
            conversation_history=conversation_history or None,
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

        await _log_audit(
            db,
            current_user.id,
            AuditAction.QUERY,
            client_ip,
            {"query_hash": query_hash},
        )
        return response

    except Exception as e:
        logger.error("query_failed", error=str(e), user_id=str(current_user.id))
        query_total.labels(status="error", cached="false").inc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Query processing failed",
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


@router.delete("/documents/{document_id}", response_model=DeleteDocumentResponse)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.DELETE_DOCUMENTS)),
    client_ip: str = Depends(get_client_ip),
):
    """Soft-delete a document and hard-delete all its chunks.

    Any authenticated user can delete their own document; ADMIN can delete any document.
    """
    from ...models.user import UserRole

    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()

    if (
        document is None
        or not document.is_active
        or document.status == DocumentStatus.DELETED
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or already deleted",
        )

    # Non-admins may only delete their own documents
    if current_user.role != UserRole.ADMIN and str(document.uploaded_by) != str(
        current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this document",
        )

    # Hard-delete all chunks
    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == document.id)
    )

    # Soft-delete the document
    document.is_active = False
    document.status = DocumentStatus.DELETED

    await db.commit()

    await _log_audit(
        db,
        current_user.id,
        AuditAction.DOCUMENT_DELETE,
        client_ip,
        {"document_id": document_id, "title": document.title},
    )

    logger.info(
        "document_deleted", document_id=document_id, user_id=str(current_user.id)
    )
    return DeleteDocumentResponse(message="Document deleted", document_id=document_id)


@router.put(
    "/documents/{document_id}/reupload",
    response_model=ReuploadDocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reupload_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.INGEST)),
    client_ip: str = Depends(get_client_ip),
):
    """Replace a document with a new file upload, incrementing its version.

    Requires at least CLINICIAN role (INGEST permission). Deletes all existing chunks,
    bumps the document version, then re-runs ingestion on the new file.
    """
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()

    if (
        document is None
        or not document.is_active
        or document.status == DocumentStatus.DELETED
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or already deleted",
        )

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

    # Save the new file to disk
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    save_path = os.path.join(
        settings.UPLOAD_DIR, f"{document_id}_v{(document.version or 0) + 1}.{ext}"
    )
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(content)

    # Hard-delete all existing chunks
    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == document.id)
    )

    # Increment version and reset document state
    new_version = (document.version or 0) + 1
    document.version = new_version
    document.filename = file.filename
    document.file_type = ext
    document.file_size = len(content)
    document.status = DocumentStatus.PENDING
    document.chunk_count = 0
    document.error_message = None
    document.indexed_at = None

    await db.commit()

    background_tasks.add_task(_process_document, document_id, save_path, ext)

    ingest_total.labels(status="accepted", file_type=ext).inc()
    await _log_audit(
        db,
        current_user.id,
        AuditAction.REINDEX,
        client_ip,
        {
            "document_id": document_id,
            "new_version": new_version,
            "filename": file.filename,
        },
    )

    logger.info(
        "document_reupload_queued",
        document_id=document_id,
        version=new_version,
        user_id=str(current_user.id),
    )
    return ReuploadDocumentResponse(
        message="Document queued for reprocessing",
        document_id=document_id,
        version=new_version,
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
        sources_result = await db.execute(
            select(QuerySource).where(QuerySource.query_id == log.id)
        )
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

    query = re.sub(
        r"(ignore previous instructions|system prompt|<[^>]+>)",
        "",
        query,
        flags=re.IGNORECASE,
    )
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


async def _log_audit(
    db: AsyncSession,
    user_id: Any,
    action: AuditAction,
    ip: str,
    details: Dict[str, Any],
) -> None:
    try:
        log = AuditLog(user_id=user_id, action=action, ip_address=ip, details=details)
        db.add(log)
        await db.commit()
    except Exception as e:
        logger.warning("audit_log_failed", error=str(e))
