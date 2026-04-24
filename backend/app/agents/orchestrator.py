"""
Orchestrator — coordinates SearchAgent → PaperService (ingest) →
ExtractAgent → SynthesisAgent → ReviewService.

Also drives the task lifecycle SSE stream:
  queued  (published by ResearchPipeline before enqueue)
  started (published here at the top of run())
  done / failed (published here at completion)
"""
import logging
import time

from app.agents.base import LLMCallBudget, init_llm_log

logger = logging.getLogger(__name__)
from app.agents.search_agent import SearchAgent
from app.agents.extract_agent import ExtractAgent
from app.agents.synthesis_agent import SynthesisAgent
from app.config import settings
from app.models.claim import Claim
from app.models.review import ReviewCreate
from app.services.paper_service import PaperService
from app.services.review_service import ReviewService
from app.services.stream_service import stream_service
from app.services.trace_service import TraceService


class Orchestrator:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.trace = TraceService()
        self.paper_service = PaperService()
        self.review_service = ReviewService()

    def run(self, topic_id: str, topic_name: str, max_papers: int = 8) -> dict:
        start_wall = time.monotonic()
        self.trace.start(self.job_id, topic_name)
        stream_service.task_started(self.job_id)

        try:
            init_llm_log(topic_name, self.job_id)
            # One shared budget for the entire job — all agents draw from it.
            budget = LLMCallBudget(settings.max_llm_calls_per_job)

            # Phase 1: Search (3 sub-queries, merged)
            search_agent = SearchAgent(self.job_id, budget=budget)
            papers_meta = search_agent.run(topic_name, max_papers=max_papers)

            if not papers_meta:
                logger.warning("SearchAgent found no papers for topic: %r", topic_name)
                synthesis_result = {
                    "synthesis": "No papers found for this topic on arXiv. Try a broader or different search term.",
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

            # Phase 2: Ingest (fetch + embed) each paper
            papers = []
            for meta in papers_meta:
                paper = self.paper_service.ingest(meta, topic_id)
                if paper:
                    papers.append(paper)

            embedded = [p for p in papers if p.embedded]
            if not embedded:
                logger.warning("Orchestrator: SearchAgent returned %d papers but none could be embedded.", len(papers))
                synthesis_result = {
                    "synthesis": "Papers were retrieved but none could be embedded for this topic. "
                                 "This may happen when arXiv returns unrelated results for an unknown search term.",
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
                total_ms = int((time.monotonic() - start_wall) * 1000)
                stats = {"total_duration_ms": total_ms, "papers_processed": 0,
                         "claims_extracted": 0, "citations_verified": 0, "citations_rejected": 0}
                self.trace.complete(self.job_id, stats)
                stream_service.task_done(self.job_id, review_id=review.id, stats=stats)
                return {"review_id": review.id, **stats}

            papers = embedded

            # Phase 3: Extract claims — reuse same agent instance across papers
            # so the shared budget is honoured without re-instantiating.
            extract_agent = ExtractAgent(self.job_id, budget=budget)
            all_claims: list[Claim] = []
            for paper in papers:
                if not paper.embedded:
                    continue
                claims = extract_agent.run(paper)
                all_claims.extend(claims)

            # Phase 4: Synthesise with citation grounding
            synthesis_result = {
                "synthesis": "",
                "citations": {},
                "cited_papers": [],
                "citations_verified": 0,
                "citations_rejected": 0,
            }
            if all_claims:
                synth_agent = SynthesisAgent(self.job_id, budget=budget)
                synthesis_result = synth_agent.run(topic_name, all_claims, papers)

            # Phase 5: Persist review
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
            self.trace.complete(self.job_id, stats)
            stream_service.task_done(self.job_id, review_id=review.id, stats=stats)
            return {"review_id": review.id, **stats}

        except Exception as exc:
            self.trace.fail(self.job_id, str(exc))
            stream_service.task_failed(self.job_id, error=str(exc))
            raise
