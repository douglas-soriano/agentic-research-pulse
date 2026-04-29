"""
RAGAS evaluation script for ResearchPulse.

Strategy:
  1. Run the pipeline ONCE with topic "retrieval augmented generation".
  2. Use the synthesis as the answer for each golden question.
  3. Retrieve question-specific contexts via semantic_search in ChromaDB.
  4. Run ragas.evaluate() with faithfulness + context_recall (+ answer_relevancy
     when using a cloud provider that supports embeddings).

Exits with code 1 if faithfulness < 0.7 or if the pipeline produced no synthesis.

Local Ollama usage:
    Add to .env:
        LLM_PROVIDER=local
        LLM_BASE_URL=http://localhost:11434/v1   # host.docker.internal won't resolve outside Docker

Usage:
    cd backend
    python scripts/eval.py
"""
import math
import os
import socket
import sys
import uuid
import warnings
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings

FAITHFULNESS_THRESHOLD = 0.7
PIPELINE_TOPIC = "retrieval augmented generation"
IS_LOCAL = settings.llm_provider == "local"

# Model used by RAGAS to score (may differ from the pipeline model).
# For local Ollama, llama3 follows JSON instructions more reliably than smaller models.
RAGAS_MODEL = os.environ.get(
    "RAGAS_LLM_MODEL",
    "llama3" if IS_LOCAL else settings.llm_model,
)

GOLDEN_QUESTIONS = [
    {
        "question": "How does Retrieval-Augmented Generation reduce hallucination in language models?",
        "ground_truth": (
            "RAG reduces hallucination by grounding generated text in retrieved documents. "
            "The model conditions on factual passages fetched from an external corpus, "
            "limiting its reliance on parametric memory and producing more accurate answers."
        ),
    },
    {
        "question": "What are the main components of a RAG pipeline?",
        "ground_truth": (
            "A RAG pipeline consists of a dense retriever that fetches relevant documents "
            "and a generative language model that conditions on those documents to produce answers."
        ),
    },
    {
        "question": "What benchmarks are used to evaluate retrieval augmented generation?",
        "ground_truth": (
            "RAG models are evaluated on open-domain QA benchmarks such as "
            "Natural Questions, TriviaQA, and WebQuestions."
        ),
    },
]


def _effective_llm_base_url() -> str:
    """Replace host.docker.internal with localhost when running outside a Docker container."""
    url = settings.llm_base_url
    if "host.docker.internal" not in url:
        return url
    try:
        socket.getaddrinfo("host.docker.internal", 80, timeout=1)
        return url  # resolvable — we're inside Docker or on Windows host
    except (socket.gaierror, OSError):
        return url.replace("host.docker.internal", "localhost")


def _setup_isolated_db():
    import app.database as db_module
    from app.database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db_module.engine = engine
    Base.metadata.create_all(engine)
    return engine


def _run_pipeline(topic_id: str) -> dict:
    from app.agents.orchestrator import Orchestrator
    from unittest.mock import patch, MagicMock

    job_id = str(uuid.uuid4())
    with patch("app.agents.orchestrator.stream_service", MagicMock()), \
         patch("app.agents.orchestrator.agent_trace") as mock_trace, \
         patch("app.agents.orchestrator.init_llm_log"):
        mock_trace.return_value.__enter__ = lambda s: s
        mock_trace.return_value.__exit__ = MagicMock(return_value=False)
        orchestrator = Orchestrator(job_id=job_id)
        return orchestrator.run(topic_id=topic_id, topic_name=PIPELINE_TOPIC, max_papers=2)


def _get_synthesis(review_id: str) -> str:
    from app.services.review_service import ReviewService

    review = ReviewService().get_by_id(review_id)
    return review.synthesis if review else ""


def _get_contexts(question: str, n: int = 10) -> list[str]:
    from app.tools.vector_tools import semantic_search

    result = semantic_search(query=question, n_results=n)
    return [chunk["text"] for chunk in result.get("chunks", [])]


def main() -> None:
    print("=" * 60)
    print("ResearchPulse RAGAS Evaluation")
    print(f"Provider: {settings.llm_provider}  Model: {settings.llm_model}")
    print("=" * 60)

    if not IS_LOCAL and not settings.llm_api_key:
        print("ERROR: LLM API key not configured.")
        sys.exit(1)

    import chromadb
    from unittest.mock import patch

    chroma_client = chromadb.EphemeralClient()
    collection = chroma_client.get_or_create_collection(
        name="paper_chunks",
        metadata={"hnsw:space": "cosine"},
    )

    with patch("app.tools.vector_tools._collection", collection):
        _setup_isolated_db()

        from app.database import get_session, TopicRow

        topic_id = str(uuid.uuid4())
        with get_session() as session:
            session.add(TopicRow(id=topic_id, name=PIPELINE_TOPIC, created_at=datetime.utcnow()))
            session.commit()

        print(f"\nRunning pipeline for topic: '{PIPELINE_TOPIC}'...")
        try:
            result = _run_pipeline(topic_id)
        except Exception as exc:
            print(f"ERROR: Pipeline failed: {exc}")
            sys.exit(1)

        synthesis = _get_synthesis(result.get("review_id", ""))

        if not synthesis or result.get("claims_extracted", 0) == 0:
            print(
                f"ERROR: Pipeline produced no claims (LLM unavailable or rate-limited?).\n"
                f"  papers_processed: {result.get('papers_processed', 0)}\n"
                f"  claims_extracted: {result.get('claims_extracted', 0)}"
            )
            sys.exit(1)

        print(f"  papers_processed:   {result.get('papers_processed', 0)}")
        print(f"  claims_extracted:   {result.get('claims_extracted', 0)}")
        print(f"  citations_verified: {result.get('citations_verified', 0)}")
        print(f"  synthesis length:   {len(synthesis)} chars")

        print(f"\nBuilding RAGAS dataset ({len(GOLDEN_QUESTIONS)} questions)...")
        rows = []
        for item in GOLDEN_QUESTIONS:
            contexts = _get_contexts(item["question"])
            if not contexts:
                print(f"  [WARN] No contexts for: {item['question'][:60]}...")
                continue
            rows.append({
                "question": item["question"],
                "answer": synthesis,
                "contexts": contexts,
                "ground_truth": item["ground_truth"],
            })
            print(f"  OK — contexts: {len(contexts)} for '{item['question'][:55]}...'")

    if not rows:
        print("\nERROR: No evaluable rows.")
        sys.exit(1)

    if IS_LOCAL:
        _eval_local(result, rows)
    else:
        _eval_ragas(rows)


def _eval_local(pipeline_result: dict, rows: list[dict]) -> None:
    """Pipeline quality checks for local Ollama — no RAGAS (local models don't produce reliable JSON)."""
    import re

    print("\n" + "=" * 60)
    print("Local Quality Check (no RAGAS for Ollama)")
    print("=" * 60)

    checks = {
        "papers_processed >= 1": pipeline_result.get("papers_processed", 0) >= 1,
        "claims_extracted >= 1":  pipeline_result.get("claims_extracted", 0) >= 1,
        "citations_verified == claims_extracted": (
            pipeline_result.get("citations_verified", 0) == pipeline_result.get("claims_extracted", 0)
        ),
        "synthesis not empty": bool(rows and rows[0].get("answer", "").strip()),
        "contexts retrieved":   all(len(r["contexts"]) > 0 for r in rows),
    }

    all_pass = True
    for name, passed in checks.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print("PASS: all local quality checks passed")
    else:
        print("FAIL: one or more quality checks failed")
        sys.exit(1)


def _eval_ragas(rows: list[dict]) -> None:
    """Full RAGAS evaluation for cloud providers."""
    print(f"\nEvaluating {len(rows)} sample(s) with RAGAS (model: {RAGAS_MODEL})...")

    try:
        from datasets import Dataset
        from ragas import evaluate
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from ragas.metrics import faithfulness, context_recall, answer_relevancy
    except ImportError as exc:
        print(f"ERROR: Missing dependency — {exc}. Run: pip install ragas datasets langchain-openai")
        sys.exit(1)

    llm_url = _effective_llm_base_url()
    ragas_llm = ChatOpenAI(
        model=RAGAS_MODEL,
        api_key=settings.llm_api_key or "ollama",
        base_url=llm_url,
    )
    ragas_embeddings = OpenAIEmbeddings(
        model="text-embedding-ada-002",
        api_key=settings.llm_api_key,
        openai_api_base=llm_url,
    )
    faithfulness.llm = ragas_llm            # type: ignore[attr-defined]
    context_recall.llm = ragas_llm          # type: ignore[attr-defined]
    answer_relevancy.llm = ragas_llm        # type: ignore[attr-defined]
    answer_relevancy.embeddings = ragas_embeddings  # type: ignore[attr-defined]

    dataset = Dataset.from_dict({
        "question":     [r["question"]     for r in rows],
        "answer":       [r["answer"]       for r in rows],
        "contexts":     [r["contexts"]     for r in rows],
        "ground_truth": [r["ground_truth"] for r in rows],
    })

    scores = evaluate(dataset, metrics=[faithfulness, answer_relevancy, context_recall])

    print("\n" + "=" * 60)
    print("RAGAS Score Table")
    print("=" * 60)
    print(f"{'Metric':<25} {'Score':>8}")
    print("-" * 35)

    df = scores.to_pandas()
    score_dict = df.select_dtypes(include="number").mean().to_dict()
    for metric in ("faithfulness", "answer_relevancy", "context_recall"):
        score = score_dict.get(metric, float("nan"))
        flag = "  *** BELOW THRESHOLD" if metric == "faithfulness" and score < FAITHFULNESS_THRESHOLD else ""
        print(f"{metric:<25} {score:>8.4f}{flag}")

    faithfulness_score = score_dict.get("faithfulness", float("nan"))
    if math.isnan(faithfulness_score):
        print("\nFAIL: faithfulness is NaN — LLM calls failed during RAGAS evaluation")
        sys.exit(1)
    if faithfulness_score < FAITHFULNESS_THRESHOLD:
        print(f"\nFAIL: faithfulness {faithfulness_score:.4f} < threshold {FAITHFULNESS_THRESHOLD}")
        sys.exit(1)

    print(f"\nPASS: faithfulness {faithfulness_score:.4f} >= threshold {FAITHFULNESS_THRESHOLD}")


if __name__ == "__main__":
    main()
