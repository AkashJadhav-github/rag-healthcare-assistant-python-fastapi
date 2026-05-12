"""
Hybrid retrieval: semantic (vector) + keyword (pg_trgm) search with RRF fusion.
Supports confidence scoring and configurable top-k.
"""

import os
import sys
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../backend"))

from app.config import settings
from app.services.metrics import retrieval_latency

from .embeddings import embedding_service
from .query_enhancer import query_enhancer

logger = structlog.get_logger()


class RetrievalResult:
    def __init__(
        self,
        chunk_id: str,
        document_id: str,
        document_title: str,
        content: str,
        similarity_score: float,
        page_number: Optional[int] = None,
        section: Optional[str] = None,
    ):
        self.chunk_id = chunk_id
        self.document_id = document_id
        self.document_title = document_title
        self.content = content
        self.similarity_score = similarity_score
        self.page_number = page_number
        self.section = section

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_title": self.document_title,
            "chunk_content": self.content,
            "similarity_score": self.similarity_score,
            "page_number": self.page_number,
            "section": self.section,
        }


class HybridRetriever:
    """Combines pgvector cosine similarity with pg_trgm keyword search using RRF."""

    def __init__(self, top_k: int = 5, similarity_threshold: float = 0.65):
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold

    async def retrieve(
        self,
        query: str,
        db: AsyncSession,
        top_k: Optional[int] = None,
        document_ids: Optional[List[str]] = None,
    ) -> List[RetrievalResult]:
        import time

        t0 = time.time()
        k = top_k or self.top_k
        enhanced_query, sub_queries = query_enhancer.enhance(query)

        all_results: Dict[str, RetrievalResult] = {}
        for sub_query in sub_queries:
            semantic = await self._semantic_search(sub_query, db, k * 2, document_ids)
            keyword = await self._keyword_search(sub_query, db, k * 2, document_ids)
            fused = self._reciprocal_rank_fusion(semantic, keyword, k)
            for r in fused:
                if (
                    r.chunk_id not in all_results
                    or r.similarity_score > all_results[r.chunk_id].similarity_score
                ):
                    all_results[r.chunk_id] = r

        results = sorted(all_results.values(), key=lambda x: x.similarity_score, reverse=True)[:k]
        filtered = [r for r in results if r.similarity_score >= self.similarity_threshold]

        retrieval_latency.observe(time.time() - t0)
        logger.info("retrieval_complete", query_len=len(query), results=len(filtered))
        return filtered

    async def _semantic_search(
        self,
        query: str,
        db: AsyncSession,
        k: int,
        document_ids: Optional[List[str]],
    ) -> List[RetrievalResult]:
        query_embedding = await embedding_service.embed_text(query)
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        params: dict = {"embedding": embedding_str, "k": k}
        query_sql = (
            "SELECT dc.id::text AS chunk_id, dc.document_id::text,"
            " d.title AS document_title, dc.content,"
            " 1 - (dc.embedding <=> :embedding::vector) AS similarity_score,"
            " dc.page_number, dc.section"
            " FROM document_chunks dc"
            " JOIN documents d ON d.id = dc.document_id"
            " WHERE d.status = 'indexed' AND d.is_active = true"
        )
        if document_ids:
            query_sql += " AND dc.document_id = ANY(:doc_ids)"
            params["doc_ids"] = document_ids
        query_sql += " ORDER BY dc.embedding <=> :embedding::vector LIMIT :k"
        sql = text(query_sql)

        result = await db.execute(sql, params)
        rows = result.fetchall()

        return [
            RetrievalResult(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                document_title=row.document_title,
                content=row.content,
                similarity_score=float(row.similarity_score),
                page_number=row.page_number,
                section=row.section,
            )
            for row in rows
        ]

    async def _keyword_search(
        self,
        query: str,
        db: AsyncSession,
        k: int,
        document_ids: Optional[List[str]],
    ) -> List[RetrievalResult]:
        kw_params: dict = {"query": query, "k": k}
        kw_sql = (
            "SELECT dc.id::text AS chunk_id, dc.document_id::text,"
            " d.title AS document_title, dc.content,"
            " similarity(dc.content, :query) AS similarity_score,"
            " dc.page_number, dc.section"
            " FROM document_chunks dc"
            " JOIN documents d ON d.id = dc.document_id"
            " WHERE d.status = 'indexed'"
            " AND d.is_active = true"
            " AND similarity(dc.content, :query) > 0.1"
        )
        if document_ids:
            kw_sql += " AND dc.document_id = ANY(:doc_ids)"
            kw_params["doc_ids"] = document_ids
        kw_sql += " ORDER BY similarity_score DESC LIMIT :k"
        sql = text(kw_sql)

        try:
            result = await db.execute(sql, kw_params)
            rows = result.fetchall()
        except Exception as e:
            logger.warning("keyword_search_failed", error=str(e))
            return []

        return [
            RetrievalResult(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                document_title=row.document_title,
                content=row.content,
                similarity_score=float(row.similarity_score) * 0.8,
                page_number=row.page_number,
                section=row.section,
            )
            for row in rows
        ]

    def _reciprocal_rank_fusion(
        self,
        semantic: List[RetrievalResult],
        keyword: List[RetrievalResult],
        k: int = 5,
        rrf_k: int = 60,
    ) -> List[RetrievalResult]:
        """Fuse ranked lists using RRF: score = sum(1 / (rrf_k + rank))."""
        scores: Dict[str, float] = {}
        index: Dict[str, RetrievalResult] = {}

        for rank, result in enumerate(semantic, start=1):
            scores[result.chunk_id] = scores.get(result.chunk_id, 0) + 1 / (rrf_k + rank)
            index[result.chunk_id] = result

        for rank, result in enumerate(keyword, start=1):
            scores[result.chunk_id] = scores.get(result.chunk_id, 0) + 1 / (rrf_k + rank)
            if result.chunk_id not in index:
                index[result.chunk_id] = result

        fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]
        for chunk_id, score in fused:
            index[chunk_id].similarity_score = min(score * 10, 1.0)

        return [index[chunk_id] for chunk_id, _ in fused]


retriever = HybridRetriever(
    top_k=settings.MAX_RETRIEVAL_DOCS,
    similarity_threshold=settings.SIMILARITY_THRESHOLD,
)
