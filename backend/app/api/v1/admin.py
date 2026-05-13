from datetime import datetime, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.rbac import Permission
from ...core.security import hash_password
from ...db.database import get_db
from ...models.audit import AuditAction, AuditLog
from ...models.document import Document, DocumentChunk, DocumentStatus
from ...models.query import QueryLog
from ...models.user import User, UserRole
from ...services.metrics import documents_indexed, vector_store_size
from ..deps import get_client_ip, require_permission

logger = structlog.get_logger()
router = APIRouter()


class ReindexResponse(BaseModel):
    status: str
    message: str
    documents_queued: int


class UserCreateRequest(BaseModel):
    email: str
    username: str
    password: str
    full_name: Optional[str] = None
    role: UserRole = UserRole.VIEWER
    department: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    full_name: Optional[str]
    role: str
    department: Optional[str]
    is_active: bool
    created_at: str


class StatsResponse(BaseModel):
    total_documents: int
    indexed_documents: int
    total_chunks: int
    total_queries: int
    active_users: int


@router.post("/reindex", response_model=ReindexResponse)
async def reindex_documents(
    background_tasks: BackgroundTasks,
    document_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.REINDEX)),
    client_ip: str = Depends(get_client_ip),
):
    """Rebuild vector indices. Pass document_id to reindex a single doc, omit for full reindex."""
    if document_id:
        result = await db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        docs_to_reindex = [doc]
    else:
        result = await db.execute(
            select(Document).where(
                Document.status.in_([DocumentStatus.INDEXED, DocumentStatus.FAILED]),
                Document.is_active,
            )
        )
        docs_to_reindex = result.scalars().all()

    for doc in docs_to_reindex:
        doc.status = DocumentStatus.PENDING
    await db.commit()

    background_tasks.add_task(_run_reindex, [str(d.id) for d in docs_to_reindex])

    log = AuditLog(
        user_id=current_user.id,
        action=AuditAction.REINDEX,
        ip_address=client_ip,
        details={"document_count": len(docs_to_reindex), "document_id": document_id},
    )
    db.add(log)
    await db.commit()

    return ReindexResponse(
        status="accepted",
        message=f"Reindexing {len(docs_to_reindex)} document(s) in the background",
        documents_queued=len(docs_to_reindex),
    )


@router.post("/users", response_model=UserResponse)
async def create_user(
    payload: UserCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.MANAGE_USERS)),
):
    from ...core.security import validate_password_strength

    if not validate_password_strength(payload.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be 8+ chars with uppercase, lowercase, digit, and special character",
        )

    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=payload.email,
        username=payload.username,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        department=payload.department,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return UserResponse(
        id=str(user.id),
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role.value,
        department=user.department,
        is_active=user.is_active,
        created_at=user.created_at.isoformat(),
    )


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(Permission.ADMIN)),
):
    """System-wide statistics for the admin dashboard."""
    from ...models.query import QueryLog

    total_docs = (await db.execute(select(func.count(Document.id)))).scalar_one()
    indexed_docs = (
        await db.execute(select(func.count(Document.id)).where(Document.status == DocumentStatus.INDEXED))
    ).scalar_one()
    total_chunks = (await db.execute(select(func.count(DocumentChunk.id)))).scalar_one()
    total_queries = (await db.execute(select(func.count(QueryLog.id)))).scalar_one()
    active_user_count = (await db.execute(select(func.count(User.id)).where(User.is_active))).scalar_one()

    documents_indexed.set(indexed_docs)
    vector_store_size.set(total_chunks)

    return StatsResponse(
        total_documents=total_docs,
        indexed_documents=indexed_docs,
        total_chunks=total_chunks,
        total_queries=total_queries,
        active_users=active_user_count,
    )


class RetentionLogStats(BaseModel):
    total: int
    expired: int
    retention_days: int


class RetentionStatsResponse(BaseModel):
    audit_logs: RetentionLogStats
    query_logs: RetentionLogStats
    policy_applied_at: str


class RetentionPurgeResponse(BaseModel):
    audit_logs_deleted: int
    query_logs_deleted: int
    purged_at: str


@router.post("/retention/purge", response_model=RetentionPurgeResponse)
async def purge_expired_logs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.ADMIN)),
    client_ip: str = Depends(get_client_ip),
):
    """Delete audit and query log rows that have exceeded their retention window."""
    now = datetime.utcnow()
    audit_cutoff = now - timedelta(days=settings.AUDIT_LOG_RETENTION_DAYS)
    query_cutoff = now - timedelta(days=settings.QUERY_LOG_RETENTION_DAYS)

    audit_result = await db.execute(
        delete(AuditLog).where(AuditLog.created_at < audit_cutoff)
    )
    audit_deleted = audit_result.rowcount

    query_result = await db.execute(
        delete(QueryLog).where(QueryLog.created_at < query_cutoff)
    )
    query_deleted = query_result.rowcount

    purged_at = now.isoformat()

    log = AuditLog(
        user_id=current_user.id,
        action=AuditAction.ADMIN_ACTION,
        ip_address=client_ip,
        details={
            "action": "retention_purge",
            "audit_logs_deleted": audit_deleted,
            "query_logs_deleted": query_deleted,
            "audit_cutoff": audit_cutoff.isoformat(),
            "query_cutoff": query_cutoff.isoformat(),
        },
    )
    db.add(log)
    await db.commit()

    logger.info(
        "retention_purge_complete",
        audit_logs_deleted=audit_deleted,
        query_logs_deleted=query_deleted,
        user_id=str(current_user.id),
    )

    return RetentionPurgeResponse(
        audit_logs_deleted=audit_deleted,
        query_logs_deleted=query_deleted,
        purged_at=purged_at,
    )


@router.get("/retention/stats", response_model=RetentionStatsResponse)
async def get_retention_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(Permission.ADMIN)),
):
    """Return counts of log rows that are expired vs. total, along with the active retention policy."""
    now = datetime.utcnow()
    audit_cutoff = now - timedelta(days=settings.AUDIT_LOG_RETENTION_DAYS)
    query_cutoff = now - timedelta(days=settings.QUERY_LOG_RETENTION_DAYS)

    audit_total = (await db.execute(select(func.count(AuditLog.id)))).scalar_one()
    audit_expired = (
        await db.execute(
            select(func.count(AuditLog.id)).where(AuditLog.created_at < audit_cutoff)
        )
    ).scalar_one()

    query_total = (await db.execute(select(func.count(QueryLog.id)))).scalar_one()
    query_expired = (
        await db.execute(
            select(func.count(QueryLog.id)).where(QueryLog.created_at < query_cutoff)
        )
    ).scalar_one()

    return RetentionStatsResponse(
        audit_logs=RetentionLogStats(
            total=audit_total,
            expired=audit_expired,
            retention_days=settings.AUDIT_LOG_RETENTION_DAYS,
        ),
        query_logs=RetentionLogStats(
            total=query_total,
            expired=query_expired,
            retention_days=settings.QUERY_LOG_RETENTION_DAYS,
        ),
        policy_applied_at=now.isoformat(),
    )


async def _run_reindex(doc_ids: list[str]) -> None:
    from app.db.database import AsyncSessionLocal
    from rag.ingestion import DocumentIngestionService

    async with AsyncSessionLocal() as db:
        ingestion = DocumentIngestionService()
        for doc_id in doc_ids:
            try:
                result = await db.execute(select(Document).where(Document.id == doc_id))
                doc = result.scalar_one_or_none()
                if doc:
                    await ingestion.reindex_document(doc_id=doc_id, db=db)
                    doc.status = DocumentStatus.INDEXED
                    await db.commit()
            except Exception as e:
                logger.error("reindex_failed", doc_id=doc_id, error=str(e))
