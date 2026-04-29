"""
Idempotency tests for process_paper_job / PaperService.ingest().

Calling ingest() twice for the same arxiv_id must produce the same number of
chunks in ChromaDB — no duplicate embedding on re-runs or retries.
"""
from unittest.mock import patch

import pytest

from app.services.paper_service import PaperService


MOCK_FULL_TEXT = (
    "Retrieval-Augmented Generation (RAG) combines a retrieval mechanism with a generative model. "
    "The retriever fetches relevant documents from a large corpus given a query. "
    "The generator then conditions on those documents to produce a factual answer. "
    "This approach significantly reduces hallucination in open-domain question answering. "
    "Experiments show consistent improvements over closed-book baselines across multiple benchmarks."
)


@patch("time.sleep")
@patch("app.services.paper_service.fetch_paper")
def test_ingest_twice_produces_same_chunk_count(mock_fetch_paper, mock_sleep, chroma_collection, test_db, sample_paper_meta, sample_topic_id):
    mock_fetch_paper.return_value = {"arxiv_id": sample_paper_meta["arxiv_id"], "text": MOCK_FULL_TEXT, "source": "ar5iv"}

    service = PaperService()
    paper_first = service.ingest(sample_paper_meta, sample_topic_id)
    count_after_first = chroma_collection.count()

    paper_second = service.ingest(sample_paper_meta, sample_topic_id)
    count_after_second = chroma_collection.count()

    assert count_after_first > 0, "No chunks were stored after first ingest"
    assert count_after_first == count_after_second, (
        f"Chunk count changed after second ingest: {count_after_first} → {count_after_second}"
    )


@patch("time.sleep")
@patch("app.services.paper_service.fetch_paper")
def test_ingest_twice_fetch_called_only_once(mock_fetch_paper, mock_sleep, chroma_collection, test_db, sample_paper_meta, sample_topic_id):
    mock_fetch_paper.return_value = {"arxiv_id": sample_paper_meta["arxiv_id"], "text": MOCK_FULL_TEXT, "source": "ar5iv"}

    service = PaperService()
    service.ingest(sample_paper_meta, sample_topic_id)
    service.ingest(sample_paper_meta, sample_topic_id)

    # fetch_paper is a network call — must not be called a second time
    assert mock_fetch_paper.call_count == 1


@patch("time.sleep")
@patch("app.services.paper_service.fetch_paper")
def test_ingest_returns_same_paper_id_on_second_call(mock_fetch_paper, mock_sleep, chroma_collection, test_db, sample_paper_meta, sample_topic_id):
    mock_fetch_paper.return_value = {"arxiv_id": sample_paper_meta["arxiv_id"], "text": MOCK_FULL_TEXT, "source": "ar5iv"}

    service = PaperService()
    paper_first = service.ingest(sample_paper_meta, sample_topic_id)
    paper_second = service.ingest(sample_paper_meta, sample_topic_id)

    assert paper_first.id == paper_second.id
