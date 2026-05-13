"""
Embedding service supporting OpenAI ada-002 and local sentence-transformers.
Includes Redis-backed caching and batch processing.
"""

import asyncio
import os
import sys
from typing import List, Optional

import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../backend"))

from app.config import settings

logger = structlog.get_logger()


class EmbeddingService:
    def __init__(self):
        self._openai_client = None
        self._local_model = None

    def _get_openai_client(self):
        if self._openai_client is None:
            from openai import AsyncOpenAI

            self._openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._openai_client

    def _get_local_model(self):
        if self._local_model is None:
            from sentence_transformers import SentenceTransformer

            self._local_model = SentenceTransformer("all-MiniLM-L6-v2")
        return self._local_model

    async def embed_text(self, text: str, use_cache: bool = True) -> List[float]:
        """Embed a single text with optional Redis caching."""
        from app.services.cache import cache_service

        cache_key = cache_service.make_embedding_key(text)

        if use_cache:
            cached = await cache_service.get(cache_key)
            if cached:
                return cached

        embedding = await self._generate_embedding(text)

        if use_cache:
            await cache_service.set(cache_key, embedding, ttl=86400)

        return embedding

    async def embed_batch(
        self, texts: List[str], batch_size: int = 50
    ) -> List[List[float]]:
        """Batch embed texts for efficient indexing."""
        results: List[Optional[List[float]]] = [None] * len(texts)

        from app.services.cache import cache_service

        uncached_indices = []
        for i, text in enumerate(texts):
            cached = await cache_service.get(cache_service.make_embedding_key(text))
            if cached:
                results[i] = cached
            else:
                uncached_indices.append(i)

        for batch_start in range(0, len(uncached_indices), batch_size):
            batch_indices = uncached_indices[batch_start : batch_start + batch_size]
            batch_texts = [texts[i] for i in batch_indices]

            embeddings = await self._generate_batch(batch_texts)

            for idx, embedding in zip(batch_indices, embeddings):
                results[idx] = embedding
                key = cache_service.make_embedding_key(texts[idx])
                await cache_service.set(key, embedding, ttl=86400)

        return [r for r in results if r is not None]

    async def _generate_embedding(self, text: str) -> List[float]:
        if settings.EMBEDDING_PROVIDER == "openai" and settings.OPENAI_API_KEY:
            return (await self._openai_embed([text]))[0]
        return (await self._local_embed([text]))[0]

    async def _generate_batch(self, texts: List[str]) -> List[List[float]]:
        if settings.EMBEDDING_PROVIDER == "openai" and settings.OPENAI_API_KEY:
            return await self._openai_embed(texts)
        return await self._local_embed(texts)

    async def _openai_embed(self, texts: List[str]) -> List[List[float]]:
        import time

        from app.services.metrics import embedding_latency

        client = self._get_openai_client()
        t0 = time.time()
        try:
            cleaned = [t.replace("\n", " ")[:8000] for t in texts]
            response = await client.embeddings.create(
                input=cleaned,
                model=settings.OPENAI_EMBEDDING_MODEL,
            )
            embedding_latency.observe(time.time() - t0)
            return [item.embedding for item in response.data]
        except Exception as e:
            logger.error("openai_embedding_failed", error=str(e))
            return await self._local_embed(texts)

    async def _local_embed(self, texts: List[str]) -> List[List[float]]:
        loop = asyncio.get_event_loop()
        model = self._get_local_model()
        embeddings = await loop.run_in_executor(
            None, lambda: model.encode(texts, show_progress_bar=False).tolist()
        )
        return embeddings

    def embedding_dimension(self) -> int:
        return settings.VECTOR_DIMENSION


embedding_service = EmbeddingService()
