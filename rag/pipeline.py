"""
Main RAG pipeline: ties together retrieval, PII masking, and LLM generation.
"""

import os
import sys
from typing import Any, Dict, List, Optional

import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../backend"))

from app.config import settings
from app.db.database import AsyncSessionLocal

from .generation import generator
from .pii_detector import pii_detector
from .retrieval import retriever

logger = structlog.get_logger()


class RAGPipeline:
    async def query(
        self,
        query: str,
        max_sources: int = 5,
        user_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Full RAG query:
        1. Sanitize + PII mask the query
        2. Retrieve relevant chunks
        3. Generate LLM response with citations
        4. Mask PHI in response
        """
        masked_query = pii_detector.mask_query(query)

        async with AsyncSessionLocal() as db:
            sources = await retriever.retrieve(
                query=masked_query,
                db=db,
                top_k=max_sources,
                document_ids=document_ids,
            )

        source_dicts = [s.to_dict() for s in sources]

        result = await generator.generate(
            query=masked_query,
            sources=source_dicts,
            max_tokens=settings.OPENAI_MAX_TOKENS,
        )

        answer, phi_found = pii_detector.mask_phi(result["answer"])
        if phi_found:
            logger.warning("phi_detected_in_response", user_id=user_id)

        return {
            "answer": answer,
            "sources": source_dicts,
            "confidence_score": result["confidence_score"],
            "model_used": result["model_used"],
            "latency_ms": result.get("latency_ms", 0),
            "phi_masked": phi_found,
        }
