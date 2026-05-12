import pytest
from rag.chunking import MedicalTextChunker, TextChunk


def test_basic_chunking():
    chunker = MedicalTextChunker(chunk_size=100, chunk_overlap=20)
    text = "This is a test sentence. " * 30
    chunks = chunker.chunk(text)
    assert len(chunks) > 1
    for c in chunks:
        assert isinstance(c, TextChunk)
        assert c.content


def test_empty_text_returns_empty():
    chunker = MedicalTextChunker()
    assert chunker.chunk("") == []
    assert chunker.chunk("   ") == []


def test_short_text_single_chunk():
    chunker = MedicalTextChunker(chunk_size=500)
    text = "Hypertension is elevated blood pressure."
    chunks = chunker.chunk(text)
    assert len(chunks) == 1
    assert chunks[0].content == text.strip()


def test_overlap_preserves_context():
    chunker = MedicalTextChunker(chunk_size=50, chunk_overlap=20)
    sentences = ["First sentence about diabetes. "] * 10 + ["Last sentence about hypertension. "] * 10
    text = "".join(sentences)
    chunks = chunker.chunk(text)
    # With overlap, words from the end of one chunk appear at start of next
    all_text = " ".join(c.content for c in chunks)
    assert "diabetes" in all_text
    assert "hypertension" in all_text


def test_chunk_index_sequential():
    chunker = MedicalTextChunker(chunk_size=80, chunk_overlap=10)
    text = "Medical information about clinical guidelines. " * 20
    chunks = chunker.chunk(text)
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i


def test_page_number_preserved():
    chunker = MedicalTextChunker(chunk_size=200)
    pages = [("Page one content about hypertension management.", 1), ("Page two content about diabetes treatment.", 2)]
    chunks = chunker.chunk_by_pages(pages)
    page_nums = [c.page_number for c in chunks]
    assert 1 in page_nums
    assert 2 in page_nums


def test_medical_abbreviation_not_split():
    chunker = MedicalTextChunker(chunk_size=500)
    text = "The patient presents with HTN and T2DM. ACE inhibitors are first-line. BP was 150/90."
    chunks = chunker.chunk(text)
    joined = " ".join(c.content for c in chunks)
    assert "HTN" in joined
    assert "T2DM" in joined
    assert "ACE" in joined


def test_token_count_populated():
    chunker = MedicalTextChunker(chunk_size=300)
    text = "Clinical guidelines for hypertension management. " * 5
    chunks = chunker.chunk(text)
    for c in chunks:
        assert c.token_count > 0
