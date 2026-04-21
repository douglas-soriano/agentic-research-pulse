"""
Orchestrator — coordinates SearchAgent → PaperService (ingest) →
ExtractAgent → SynthesisAgent → ReviewService.

Also drives the task lifecycle SSE stream:
  queued  (published by ResearchPipeline before enqueue)
  started (published here at the top of run())
  done / failed (published here at completion)
"""
import time

from app.agents.search_agent import SearchAgent
from app.agents.extract_agent import ExtractAgent
from app.agents.synthesis_agent import SynthesisAgent
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
            # Phase 1: Search (3 sub-queries, merged)
            search_agent = SearchAgent(self.job_id)
            papers_meta = search_agent.run(topic_name, max_papers=max_papers)

            if not papers_meta:
                raise RuntimeError("SearchAgent returned no papers")

            # Phase 2: Ingest (fetch + embed) each paper
            papers = []
            for meta in papers_meta:
                paper = self.paper_service.ingest(meta, topic_id)
                if paper:
                    papers.append(paper)

            # Phase 3: Extract claims from each embedded paper
            extract_agent = ExtractAgent(self.job_id)
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
                synth_agent = SynthesisAgent(self.job_id)
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
