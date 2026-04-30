import re
import time

import structlog

from app.agents.base import LLMCallBudget, init_llm_log
from app.agents.search_agent import SearchAgent
from app.agents.extract_agent import ExtractAgent
from app.agents.synthesis_agent import SynthesisAgent
from app.config import settings
from app.models.claim import Claim
from app.models.review import ReviewCreate
from app.observability.langsmith import agent_trace
from app.services.paper_service import PaperService
from app.services.review_service import ReviewService
from app.services.stream_service import stream_service
from app.services.topic_service import TopicService
from app.services.trace_service import TraceService

logger = structlog.get_logger(__name__)


class Orchestrator:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.trace = TraceService()
        self.paper_service = PaperService()
        self.review_service = ReviewService()
        self.topic_service = TopicService()

    @staticmethod
    def _papers_are_relevant(topic: str, papers_meta: list[dict]) -> bool:
        _STOPWORDS = {
            "for", "in", "of", "the", "a", "an", "and", "or", "with",
            "on", "at", "to", "is", "are", "by", "from", "using", "via",
            "based", "approach", "method", "methods", "new", "novel",
        }

        raw_tokens = re.findall(r"[A-Za-z0-9]+", topic)
        significant: list[str] = []
        for tok in raw_tokens:
            low = tok.lower()
            if low in _STOPWORDS:
                continue
            if (any(c.isdigit() for c in tok)
                    or (tok.isupper() and len(tok) >= 2)
                    or len(tok) >= 7):
                significant.append(low)

        if not significant:
            return True

        for paper in papers_meta:
            corpus = (
                paper.get("title", "") + " " + paper.get("abstract", "")
            ).lower()
            if any(tok in corpus for tok in significant):
                return True

        logger.warning(
            "irrelevant_papers",
            significant_tokens=significant,
            topic=topic,
            agent="orchestrator",
            job_id=self.job_id,
        )
        return False

    def run(self, topic_id: str, topic_name: str, max_papers: int = 8) -> dict:
        bound_log = logger.bind(job_id=self.job_id, agent_name="orchestrator", step="start")
        start_wall = time.monotonic()

        with agent_trace(
            "pipeline_run",
            run_type="chain",
            job_id=self.job_id,
            topic=topic_name,
            max_papers=max_papers,
        ):
            self.trace.start(self.job_id, topic_name)
            stream_service.task_started(self.job_id)
            bound_log.info("pipeline_started", topic=topic_name)

            try:
                init_llm_log(topic_name, self.job_id)
                budget = LLMCallBudget(settings.max_llm_calls_per_job)


                with agent_trace("search_phase", run_type="chain", job_id=self.job_id, topic=topic_name):
                    search_agent = SearchAgent(self.job_id, budget=budget)
                    papers_meta = search_agent.run(topic_name, max_papers=max_papers)

                if papers_meta and not self._papers_are_relevant(topic_name, papers_meta):
                    papers_meta = []

                if not papers_meta:
                    logger.warning(
                        "no_papers_found",
                        topic=topic_name,
                        agent_name="orchestrator",
                        job_id=self.job_id,
                        step="search",
                    )
                    synthesis_result = {
                        "synthesis": "No papers found for this topic. Try a broader or different search term.",
                        "citations": {},
                        "cited_papers": [],
                        "citations_verified": 0,
                        "citations_rejected": 0,
                    }
                    review = self.review_service.save(
                        ReviewCreate(
                            topic_id=topic_id,
                            topic_name=topic_name,
                            synthesis=synthesis_result["synthesis"],
                            citations={},
                            cited_papers=[],
                            papers_processed=0,
                            claims_extracted=0,
                            citations_verified=0,
                            citations_rejected=0,
                        )
                    )
                    self.topic_service.mark_fetched(topic_id)
                    total_ms = int((time.monotonic() - start_wall) * 1000)
                    stats = {
                        "total_duration_ms": total_ms,
                        "papers_processed": 0,
                        "claims_extracted": 0,
                        "citations_verified": 0,
                        "citations_rejected": 0,
                    }
                    self.trace.complete(self.job_id, stats)
                    stream_service.task_done(self.job_id, review_id=review.id, stats=stats)
                    return {"review_id": review.id, **stats}


                papers = []
                with agent_trace("ingest_phase", run_type="chain", job_id=self.job_id, papers_count=len(papers_meta)):
                    for meta in papers_meta:
                        paper = self.paper_service.ingest(meta, topic_id)
                        if paper:
                            papers.append(paper)

                embedded = [p for p in papers if p.embedded]
                if not embedded:
                    logger.warning(
                        "no_embedded_papers",
                        total_papers=len(papers),
                        agent_name="orchestrator",
                        job_id=self.job_id,
                        step="ingest",
                    )
                    synthesis_result = {
                        "synthesis": "Papers were retrieved but none could be embedded for this topic. "
                                     "This may happen when the search providers return unrelated results for an unknown search term.",
                        "citations": {},
                        "cited_papers": [],
                        "citations_verified": 0,
                        "citations_rejected": 0,
                    }
                    review = self.review_service.save(
                        ReviewCreate(
                            topic_id=topic_id, topic_name=topic_name,
                            synthesis=synthesis_result["synthesis"],
                            citations={}, cited_papers=[],
                            papers_processed=0, claims_extracted=0,
                            citations_verified=0, citations_rejected=0,
                        )
                    )
                    self.topic_service.mark_fetched(topic_id)
                    total_ms = int((time.monotonic() - start_wall) * 1000)
                    stats = {
                        "total_duration_ms": total_ms,
                        "papers_processed": 0,
                        "claims_extracted": 0,
                        "citations_verified": 0,
                        "citations_rejected": 0,
                    }
                    self.trace.complete(self.job_id, stats)
                    stream_service.task_done(self.job_id, review_id=review.id, stats=stats)
                    return {"review_id": review.id, **stats}

                papers = embedded


                with agent_trace("extract_phase", run_type="chain", job_id=self.job_id, papers_count=len(papers)):
                    extract_agent = ExtractAgent(self.job_id, budget=budget)
                    all_claims: list[Claim] = []
                    for paper in papers:
                        if not paper.embedded:
                            continue
                        claims = extract_agent.run(paper)
                        all_claims.extend(claims)


                synthesis_result = {
                    "synthesis": (
                        "No claims could be extracted from the retrieved papers. "
                        "The papers may not contain enough structured content, "
                        "or try a more specific search term."
                    ),
                    "citations": {},
                    "cited_papers": [],
                    "citations_verified": 0,
                    "citations_rejected": 0,
                }
                if all_claims:
                    with agent_trace("synthesis_phase", run_type="chain", job_id=self.job_id, claims_count=len(all_claims)):
                        synth_agent = SynthesisAgent(self.job_id, budget=budget)
                        synthesis_result = synth_agent.run(topic_name, all_claims, papers)


                review = self.review_service.save(
                    ReviewCreate(
                        topic_id=topic_id,
                        topic_name=topic_name,
                        synthesis=synthesis_result["synthesis"],
                        citations=synthesis_result["citations"],
                        cited_papers=synthesis_result["cited_papers"],
                        papers_processed=len(papers),
                        claims_extracted=len(all_claims),
                        citations_verified=synthesis_result["citations_verified"],
                        citations_rejected=synthesis_result["citations_rejected"],
                    )
                )

                total_ms = int((time.monotonic() - start_wall) * 1000)
                stats = {
                    "total_duration_ms": total_ms,
                    "papers_processed": len(papers),
                    "claims_extracted": len(all_claims),
                    "citations_verified": synthesis_result["citations_verified"],
                    "citations_rejected": synthesis_result["citations_rejected"],
                }
                self.topic_service.mark_fetched(topic_id)
                self.trace.complete(self.job_id, stats)
                stream_service.task_done(self.job_id, review_id=review.id, stats=stats)

                bound_log.info(
                    "pipeline_completed",
                    total_duration_ms=total_ms,
                    papers_processed=len(papers),
                    claims_extracted=len(all_claims),
                    citations_verified=synthesis_result["citations_verified"],
                )
                return {"review_id": review.id, **stats}

            except Exception as exc:
                logger.error(
                    "pipeline_failed",
                    error=str(exc),
                    agent_name="orchestrator",
                    job_id=self.job_id,
                    step="unknown",
                )
                self.trace.fail(self.job_id, str(exc))
                stream_service.task_failed(self.job_id, error=str(exc))
                raise
