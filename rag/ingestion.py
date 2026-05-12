"""
Document ingestion pipeline: parse → chunk → embed → store in pgvector.
Supports PDF, DOCX, TXT, MD.
"""

import asyncio
import hashlib
import os
import tempfile
from typing import List

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .chunking import MedicalTextChunker, TextChunk
from .embeddings import embedding_service

logger = structlog.get_logger()


class DocumentParser:
    """Parse documents of various formats into raw text with page metadata."""

    async def parse(self, file_path: str, file_type: str) -> List[tuple[str, int]]:
        """Return list of (text, page_number) tuples."""
        parsers = {
            "pdf": self._parse_pdf,
            "docx": self._parse_docx,
            "txt": self._parse_text,
            "md": self._parse_text,
        }
        parser = parsers.get(file_type.lower())
        if not parser:
            raise ValueError(f"Unsupported file type: {file_type}")
        return await parser(file_path)

    async def _parse_pdf(self, path: str) -> List[tuple[str, int]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._parse_pdf_sync, path)

    def _parse_pdf_sync(self, path: str) -> List[tuple[str, int]]:
        from pypdf import PdfReader

        reader = PdfReader(path)
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append((text, i))
        return pages

    async def _parse_docx(self, path: str) -> List[tuple[str, int]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._parse_docx_sync, path)

    def _parse_docx_sync(self, path: str) -> List[tuple[str, int]]:
        from docx import Document

        doc = Document(path)
        full_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return [(full_text, 1)]

    async def _parse_text(self, path: str) -> List[tuple[str, int]]:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return [(content, 1)]


class DocumentIngestionService:
    def __init__(self):
        self.parser = DocumentParser()
        self.chunker = MedicalTextChunker()

    async def ingest(self, doc_id: str, file_path: str, file_type: str, db: AsyncSession) -> int:
        """Full ingestion pipeline. Returns number of chunks created."""
        logger.info("ingestion_start", doc_id=doc_id, file_type=file_type)

        pages = await self.parser.parse(file_path, file_type)
        chunks = self.chunker.chunk_by_pages(pages)
        logger.info("chunks_created", doc_id=doc_id, count=len(chunks))

        if not chunks:
            raise ValueError("Document produced no text chunks")

        await self._store_chunks(doc_id, chunks, db)
        logger.info("ingestion_complete", doc_id=doc_id, chunk_count=len(chunks))
        return len(chunks)

    async def reindex_document(self, doc_id: str, db: AsyncSession) -> int:
        """Delete existing chunks and re-embed the document from stored content."""
        from backend.app.models.document import DocumentChunk

        await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))
        await db.commit()

        from backend.app.models.document import Document

        result = await db.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            raise ValueError(f"Document {doc_id} not found")

        tmp_path = os.path.join(tempfile.gettempdir(), f"reindex_{doc_id}")
        if not os.path.exists(tmp_path):
            raise FileNotFoundError(f"Source file not found for reindex: {doc_id}")

        return await self.ingest(doc_id, tmp_path, doc.file_type, db)

    async def _store_chunks(self, doc_id: str, chunks: List[TextChunk], db: AsyncSession) -> None:
        texts = [c.content for c in chunks]
        embeddings = await embedding_service.embed_batch(texts)

        import uuid

        from backend.app.models.document import DocumentChunk

        chunk_objects = []
        for chunk, embedding in zip(chunks, embeddings):
            content_hash = hashlib.sha256(chunk.content.encode()).hexdigest()
            obj = DocumentChunk(
                id=uuid.uuid4(),
                document_id=doc_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                content_hash=content_hash,
                embedding=embedding,
                token_count=chunk.token_count,
                page_number=chunk.page_number,
                section=chunk.section,
                metadata=chunk.metadata or {},
            )
            chunk_objects.append(obj)

        db.add_all(chunk_objects)
        await db.commit()
