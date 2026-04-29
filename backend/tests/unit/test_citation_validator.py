"""
Unit tests for verify_citation.
ChromaDB calls are mocked via the chroma_collection fixture (ephemeral client).
"""
import pytest

from app.tools.synthesis_tools import verify_citation


def test_verify_citation_rejects_nonexistent_chunk_id(chroma_collection):
    result = verify_citation("nonexistent::chunk::999", "some-paper-id")

    assert result["verified"] is False
    assert "not found" in result["reason"]


def test_verify_citation_accepts_existing_chunk(chroma_collection):
    chroma_collection.upsert(
        ids=["paper1::chunk::0"],
        documents=["RAG improves factuality."],
        metadatas=[{"paper_id": "paper-abc"}],
    )

    result = verify_citation("paper1::chunk::0", "paper-abc")

    assert result["verified"] is True
    assert result["chunk_id"] == "paper1::chunk::0"


def test_verify_citation_rejects_chunk_belonging_to_different_paper(chroma_collection):
    chroma_collection.upsert(
        ids=["paper1::chunk::0"],
        documents=["Dense retrieval outperforms BM25."],
        metadatas=[{"paper_id": "paper-abc"}],
    )

    result = verify_citation("paper1::chunk::0", "paper-xyz")

    assert result["verified"] is False
    assert "paper-abc" in result["reason"]


def test_verify_citation_returns_chunk_id_in_response(chroma_collection):
    result = verify_citation("ghost::chunk::0", "paper-1")

    assert result["chunk_id"] == "ghost::chunk::0"
