"""
Healthcare-aware text chunking with overlapping windows for context retention.
Uses sentence boundaries to avoid splitting mid-sentence.
"""

import re
from dataclasses import dataclass
from typing import List, Optional

import tiktoken


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    token_count: int
    page_number: Optional[int] = None
    section: Optional[str] = None
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class MedicalTextChunker:
    """Overlap-based chunker that respects sentence and paragraph boundaries."""

    SECTION_HEADERS = re.compile(
        r"^(Abstract|Introduction|Methods?|Results?|Discussion|Conclusion|References?|"
        r"Background|Diagnosis|Treatment|Prognosis|Epidemiology|Pathophysiology|"
        r"Clinical Presentation|Management|Guidelines?|Protocol|Summary)\b",
        re.IGNORECASE | re.MULTILINE,
    )

    def __init__(
        self, chunk_size: int = 400, chunk_overlap: int = 80, model: str = "cl100k_base"
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        try:
            self.tokenizer = tiktoken.get_encoding(model)
        except Exception:
            self.tokenizer = None

    def _count_tokens(self, text: str) -> int:
        if self.tokenizer:
            return len(self.tokenizer.encode(text))
        return len(text) // 4

    def _split_into_sentences(self, text: str) -> List[str]:
        """Split on sentence boundaries and paragraph/line breaks for medical text."""
        text = re.sub(r"\n{3,}", "\n\n", text)
        # First split on paragraph breaks
        paragraphs = re.split(r"\n{2,}", text)
        sentences = []
        for para in paragraphs:
            # Within each paragraph, split on sentence-ending punctuation
            parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", para)
            # Also split on newlines (for bullet lists, numbered items)
            for part in parts:
                lines = [ln.strip() for ln in part.split("\n") if ln.strip()]
                sentences.extend(lines)
        return sentences

    def _detect_section(self, text: str) -> Optional[str]:
        match = self.SECTION_HEADERS.search(text[:200])
        return match.group(0).strip() if match else None

    def chunk(self, text: str, page_number: Optional[int] = None) -> List[TextChunk]:
        """Split text into overlapping chunks respecting token budget."""
        if not text or not text.strip():
            return []

        sentences = self._split_into_sentences(text)
        chunks: List[TextChunk] = []
        current_sentences: List[str] = []
        current_tokens = 0
        chunk_index = 0

        for sentence in sentences:
            sentence_tokens = self._count_tokens(sentence)

            if sentence_tokens > self.chunk_size:
                if current_sentences:
                    content = " ".join(current_sentences)
                    chunks.append(
                        TextChunk(
                            content=content,
                            chunk_index=chunk_index,
                            token_count=current_tokens,
                            page_number=page_number,
                            section=self._detect_section(content),
                        )
                    )
                    chunk_index += 1
                    current_sentences, current_tokens = [], 0

                words = sentence.split()
                for i in range(0, len(words), self.chunk_size // 2):
                    fragment = " ".join(words[i : i + self.chunk_size // 2])
                    chunks.append(
                        TextChunk(
                            content=fragment,
                            chunk_index=chunk_index,
                            token_count=self._count_tokens(fragment),
                            page_number=page_number,
                        )
                    )
                    chunk_index += 1
                continue

            if current_tokens + sentence_tokens > self.chunk_size and current_sentences:
                content = " ".join(current_sentences)
                chunks.append(
                    TextChunk(
                        content=content,
                        chunk_index=chunk_index,
                        token_count=current_tokens,
                        page_number=page_number,
                        section=self._detect_section(content),
                    )
                )
                chunk_index += 1

                overlap_sentences: List[str] = []
                overlap_tokens = 0
                for s in reversed(current_sentences):
                    t = self._count_tokens(s)
                    if overlap_tokens + t <= self.chunk_overlap:
                        overlap_sentences.insert(0, s)
                        overlap_tokens += t
                    else:
                        break

                current_sentences = overlap_sentences
                current_tokens = overlap_tokens

            current_sentences.append(sentence)
            current_tokens += sentence_tokens

        if current_sentences:
            content = " ".join(current_sentences)
            chunks.append(
                TextChunk(
                    content=content,
                    chunk_index=chunk_index,
                    token_count=current_tokens,
                    page_number=page_number,
                    section=self._detect_section(content),
                )
            )

        return chunks

    def chunk_by_pages(self, pages: List[tuple[str, int]]) -> List[TextChunk]:
        """Chunk a list of (text, page_number) tuples, preserving page metadata."""
        all_chunks: List[TextChunk] = []
        global_idx = 0
        for text, page_num in pages:
            for chunk in self.chunk(text, page_number=page_num):
                chunk.chunk_index = global_idx
                all_chunks.append(chunk)
                global_idx += 1
        return all_chunks
