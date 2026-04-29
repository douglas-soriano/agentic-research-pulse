import os
import re
import uuid

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def skip_without_api_key():
    from app.config import settings
    if not settings.gemini_api_key:
        pytest.skip("GEMINI_API_KEY not set — skipping integration test")


TOPIC = "retrieval augmented generation"


def test_full_pipeline_end_to_end(chroma_collection, test_db):
    from app.agents.orchestrator import Orchestrator
    from app.database import TopicRow
    from app.database import get_session
    from app.database import init_db

    init_db()

    topic_id = str(uuid.uuid4())
    with get_session() as session:
        from app.utils.time import utc_now
        topic = TopicRow(id=topic_id, name=TOPIC, created_at=utc_now())
        session.add(topic)
        session.commit()

    job_id = str(uuid.uuid4())

    from app.config import settings
    from unittest.mock import patch, MagicMock


    gemini_only = [settings.get_provider_chain()[0]]

    mock_stream = MagicMock()
    with patch("app.agents.orchestrator.stream_service", mock_stream),\
         patch("app.agents.orchestrator.agent_trace") as mock_trace,\
         patch("app.agents.orchestrator.init_llm_log"),\
         patch("app.config.Settings.get_provider_chain", return_value=gemini_only):
        mock_trace.return_value.__enter__ = lambda s: s
        mock_trace.return_value.__exit__ = MagicMock(return_value=False)

        orchestrator = Orchestrator(job_id=job_id)
        result = orchestrator.run(topic_id=topic_id, topic_name=TOPIC, max_papers=2)


    assert result["papers_processed"] >= 1, (
        f"Expected at least 1 paper to be processed, got {result['papers_processed']}"
    )

    assert result["claims_extracted"] >= 1, (
        f"Expected at least 1 claim to be extracted, got {result['claims_extracted']}"
    )

    assert result["citations_verified"] >= 1, (
        f"Expected at least 1 verified citation, got {result['citations_verified']}"
    )

    assert result["citations_verified"] == result["claims_extracted"], (
        "citations_verified must equal claims_extracted — hallucinated chunk_ids must "
        f"not slip through. Got verified={result['citations_verified']}, "
        f"extracted={result['claims_extracted']}"
    )


    from app.services.review_service import ReviewService
    review_service = ReviewService()
    review = review_service.get_by_id(result["review_id"])

    assert review is not None
    assert review.synthesis, "Review synthesis text must not be empty"

    citation_tokens = re.findall(r"\[citation_(\d{4})\]", review.synthesis)
    for token in citation_tokens:
        assert token in review.citations, (
            f"[citation_{token}] appears in synthesis but has no entry in citations map"
        )
