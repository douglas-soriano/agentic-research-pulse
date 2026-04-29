"""
Unit tests for extract_claims.
No external dependencies — purely deterministic validation logic.
"""
import pytest

from app.tools.synthesis_tools import extract_claims


def test_extract_claims_returns_all_valid_chunks():
    chunks = [
        {"chunk_id": "paper1::chunk::0", "text": "RAG improves factuality.", "category": "finding", "confidence": 0.9},
        {"chunk_id": "paper1::chunk::1", "text": "Dense retrieval outperforms BM25.", "category": "finding", "confidence": 0.85},
        {"chunk_id": "paper1::chunk::2", "text": "Limitations include retrieval latency.", "category": "limitation"},
    ]

    result = extract_claims("paper1", chunks)

    assert result["count"] == 3
    assert len(result["claims"]) == 3


def test_extract_claims_all_returned_claims_have_chunk_id_from_input():
    input_chunk_ids = {"paper1::chunk::0", "paper1::chunk::1"}
    chunks = [
        {"chunk_id": "paper1::chunk::0", "text": "Finding A."},
        {"chunk_id": "paper1::chunk::1", "text": "Finding B."},
    ]

    result = extract_claims("paper1", chunks)

    for claim in result["claims"]:
        assert claim["chunk_id"] in input_chunk_ids


def test_extract_claims_filters_out_chunks_without_chunk_id():
    chunks = [
        {"chunk_id": "paper1::chunk::0", "text": "Valid claim."},
        {"text": "No chunk_id here."},
        {"chunk_id": "", "text": "Empty chunk_id."},
    ]

    result = extract_claims("paper1", chunks)

    assert result["count"] == 1
    assert result["claims"][0]["chunk_id"] == "paper1::chunk::0"


def test_extract_claims_filters_out_chunks_without_text():
    chunks = [
        {"chunk_id": "paper1::chunk::0", "text": "Valid claim."},
        {"chunk_id": "paper1::chunk::1"},
        {"chunk_id": "paper1::chunk::2", "text": ""},
    ]

    result = extract_claims("paper1", chunks)

    assert result["count"] == 1


def test_extract_claims_defaults_category_to_finding():
    chunks = [{"chunk_id": "paper1::chunk::0", "text": "Some finding."}]

    result = extract_claims("paper1", chunks)

    assert result["claims"][0]["category"] == "finding"


def test_extract_claims_defaults_confidence_to_0_8():
    chunks = [{"chunk_id": "paper1::chunk::0", "text": "Some finding."}]

    result = extract_claims("paper1", chunks)

    assert result["claims"][0]["confidence"] == pytest.approx(0.8)


def test_extract_claims_preserves_paper_id():
    chunks = [{"chunk_id": "paper1::chunk::0", "text": "Some finding."}]

    result = extract_claims("paper-xyz", chunks)

    assert result["claims"][0]["paper_id"] == "paper-xyz"


def test_extract_claims_empty_input_returns_zero():
    result = extract_claims("paper1", [])

    assert result["count"] == 0
    assert result["claims"] == []
