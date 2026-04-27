"""
SynthesisAgent — synthesizes a living review from verified claims.

Citation format:
  Inline tokens:  [citation_0001], [citation_0002], …
  Returned map:   {"0001": {paper_id, arxiv_id, title, authors, chunk_id}, …}

Claims are pre-verified in Python before the LLM sees them, so the model
only needs to write text — no tool calls required during synthesis.
"""
import json
import re
import time

import structlog

from app.agents.base import BaseAgent, LLMCallBudget
from app.models.agent_outputs import SynthesisOutput
from app.models.claim import Claim
from app.models.paper import Paper
from app.models.review import CitedPaper
from app.observability.langsmith import agent_trace
from app.tools.synthesis_tools import verify_citation

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = """You are a scientific synthesis agent producing a living literature review.

You will receive a list of pre-verified claims, each tagged with a citation token like [citation_0001].

TASK:
Write a 4–6 paragraph synthesis covering: main themes, key findings, methodological patterns, and open problems.
Use [citation_XXXX] tokens inline to reference the claims.

OUTPUT FORMAT — return ONLY this JSON, no prose, no markdown:
{
  "synthesis": "<text with [citation_XXXX] tokens inline>"
}

RULES:
- Use the exact citation tokens provided — do not invent new ones.
- Place each [citation_XXXX] token immediately AFTER the sentence or clause it supports, not before.
- Never place multiple citation tokens consecutively at the start of a paragraph.
- Every sentence about a specific finding should reference at least one citation.
- The synthesis should read as a coherent academic review, not a list of bullet points."""


class SynthesisAgent(BaseAgent):
    agent_name = "synthesis_agent"

    def __init__(self, job_id: str, budget: LLMCallBudget | None = None):
        super().__init__(job_id, budget=budget)
        self.tools = []
        self.tool_map = {}

    def run(
        self,
        topic: str,
        claims: list[Claim],
        papers: list[Paper],
    ) -> dict:
        bound_log = logger.bind(job_id=self.job_id, agent_name=self.agent_name)
        paper_map = {p.id: p for p in papers}

        with agent_trace(
            "synthesis_agent",
            run_type="chain",
            job_id=self.job_id,
            topic=topic,
            claims_count=len(claims),
        ):
            # Pre-verify claims programmatically
            t0 = time.monotonic()
            verified_items: list[dict] = []
            rejected_count = 0
            for claim in claims:
                result = verify_citation(claim.chunk_id, claim.paper_id)
                if result["verified"]:
                    key = f"{len(verified_items) + 1:04d}"
                    paper = paper_map.get(claim.paper_id)
                    verified_items.append({
                        "key": key,
                        "claim": claim,
                        "paper": paper,
                    })
                else:
                    rejected_count += 1

            self.trace.record_step(
                job_id=self.job_id,
                agent=self.agent_name,
                tool="verify_citations",
                input_data={"claims_received": len(claims)},
                output_data={"verified": len(verified_items), "rejected": rejected_count},
                duration_ms=int((time.monotonic() - t0) * 1000),
                success=True,
            )
            bound_log.info(
                "citations_verified",
                verified=len(verified_items),
                rejected=rejected_count,
                step="verify_citations",
            )

            # Build citation map
            citations: dict[str, dict] = {}
            for item in verified_items:
                paper = item["paper"]
                citations[item["key"]] = {
                    "paper_id": item["claim"].paper_id,
                    "arxiv_id": paper.arxiv_id if paper else "",
                    "title": paper.title if paper else "",
                    "authors": paper.authors[:3] if paper else [],
                    "chunk_id": item["claim"].chunk_id,
                }

            if not verified_items:
                return {
                    "synthesis": (
                        "No verifiable claims could be extracted from the ingested papers for this topic. "
                        "This may occur when paper full-text is unavailable and only abstracts were indexed."
                    ),
                    "citations": {},
                    "cited_papers": [],
                    "citations_verified": 0,
                    "citations_rejected": rejected_count,
                }

            claims_list = [
                {
                    "citation": f"[citation_{item['key']}]",
                    "text": item["claim"].text,
                    "category": item["claim"].category,
                    "paper_title": item["paper"].title if item["paper"] else "",
                }
                for item in verified_items
            ]

            messages = [
                {
                    "role": "user",
                    "content": (
                        f"Topic: '{topic}'\n\n"
                        f"Pre-verified claims ({len(claims_list)} total):\n"
                        f"{json.dumps(claims_list, indent=2)}\n\n"
                        f"Write a synthesis using the [citation_XXXX] tokens above. "
                        f"Return ONLY the JSON object."
                    ),
                }
            ]

            t1 = time.monotonic()
            synthesis, usage = self._synthesize_with_structured(messages)
            duration_ms = int((time.monotonic() - t1) * 1000)

            used_citations = {
                k: v for k, v in citations.items()
                if f"[citation_{k}]" in synthesis
            }

            cited_papers = self._build_cited_papers(used_citations, papers)

            self.trace.record_step(
                job_id=self.job_id,
                agent=self.agent_name,
                tool="synthesize",
                input_data={"verified_claims": len(verified_items)},
                output_data={"citations_used": len(used_citations), "synthesis_chars": len(synthesis)},
                duration_ms=duration_ms,
                success=True,
                token_count=usage.get("total_tokens"),
                cost_usd=usage.get("cost_usd"),
            )
            bound_log.info(
                "synthesis_done",
                citations_used=len(used_citations),
                synthesis_chars=len(synthesis),
                token_count=usage.get("total_tokens"),
                cost_usd=usage.get("cost_usd"),
                step="synthesize",
            )

            return {
                "synthesis": synthesis,
                "citations": used_citations,
                "cited_papers": cited_papers,
                "citations_verified": len(used_citations),
                "citations_rejected": rejected_count,
            }

    def _synthesize_with_structured(self, messages: list[dict]) -> tuple[str, dict]:
        output, usage = self._run_structured(
            SynthesisOutput,
            messages=messages,
            system=SYSTEM_PROMPT,
            max_retries=2,
            phase_tool="synthesize",
        )
        text = re.sub(r'\[\s*citation_(\d{4})\s*\]', r'[citation_\1]', output.synthesis)
        return text, usage

    def _build_cited_papers(
        self,
        citations: dict[str, dict],
        papers: list[Paper],
    ) -> list[CitedPaper]:
        paper_map = {p.id: p for p in papers}
        paper_chunks: dict[str, set[str]] = {}
        for entry in citations.values():
            pid = entry.get("paper_id", "")
            cid = entry.get("chunk_id", "")
            if pid and cid:
                paper_chunks.setdefault(pid, set()).add(cid)

        cited = []
        for paper_id, chunk_ids in paper_chunks.items():
            paper = paper_map.get(paper_id)
            if paper:
                cited.append(CitedPaper(
                    paper_id=paper.id,
                    arxiv_id=paper.arxiv_id,
                    title=paper.title,
                    authors=paper.authors,
                    chunk_ids=list(chunk_ids),
                ))
        return cited
