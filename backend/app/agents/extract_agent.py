"""
ExtractAgent — extracts structured claims from a paper.

Python controls chunk_ids entirely:
  1. semantic_search is called in Python (not via tool) to get real chunks.
  2. The LLM is given the chunks by index and asked only to write claim text.
  3. Python maps each index back to the real chunk_id.
"""
import json
import time

import structlog

from app.agents.base import BaseAgent, LLMCallBudget
from app.models.agent_outputs import ClaimsOutput
from app.models.paper import Paper
from app.models.claim import Claim
from app.observability.langsmith import agent_trace
from app.tools.vector_tools import semantic_search

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = """You are a scientific claim extraction assistant.

You will receive a list of text chunks from a research paper, each labeled with an index number.

For each chunk that contains meaningful scientific content (findings, methods, contributions, or limitations),
write a concise 1–2 sentence claim summarising the key point.

Skip chunks that are:
- Navigation text, headers, or HTML boilerplate
- Reference lists or citations only
- Very short or uninformative

Return ONLY this JSON — no prose, no markdown:
{"claims": [{"index": <int>, "text": "<claim>", "category": "<finding|method|limitation|contribution>", "confidence": <0.0-1.0>}]}

Use only the index numbers provided. Do not invent new index values."""


class ExtractAgent(BaseAgent):
    agent_name = "extract_agent"

    MAX_CHUNKS_PER_PAPER = 8

    def __init__(self, job_id: str, budget: LLMCallBudget | None = None):
        super().__init__(job_id, budget=budget)
        self.tools = []
        self.tool_map = {}

    def run(self, paper: Paper) -> list[Claim]:
        bound_log = logger.bind(
            job_id=self.job_id,
            agent_name=self.agent_name,
            paper_id=paper.id,
            arxiv_id=paper.arxiv_id,
        )

        with agent_trace(
            "extract_agent",
            run_type="chain",
            job_id=self.job_id,
            paper_id=paper.id,
            paper_title=paper.title,
        ):
            # Step 1: fetch chunks from ChromaDB
            t0 = time.monotonic()
            chunks = self._fetch_chunks(paper)
            self.trace.record_step(
                job_id=self.job_id,
                agent=self.agent_name,
                tool="semantic_search",
                input_data={"paper_id": paper.id, "title": paper.title},
                output_data={"chunks_found": len(chunks)},
                duration_ms=int((time.monotonic() - t0) * 1000),
                success=True,
            )
            bound_log.info("chunks_fetched", chunks_found=len(chunks), step="semantic_search")

            if not chunks:
                bound_log.info("no_chunks", step="semantic_search")
                return []

            # Step 2: ask LLM to write claim text only
            chunks_payload = [
                {"index": i, "text": c["text"][:600]}
                for i, c in enumerate(chunks)
            ]

            messages = [
                {
                    "role": "user",
                    "content": (
                        f"Paper: {paper.title}\n"
                        f"Authors: {', '.join(paper.authors[:3])}\n"
                        f"Abstract: {paper.abstract[:300]}\n\n"
                        f"Chunks ({len(chunks)} total):\n"
                        f"{json.dumps(chunks_payload, indent=2)}\n\n"
                        f"Extract claims from the chunks above. Return JSON only."
                    ),
                }
            ]

            t1 = time.monotonic()
            claims, usage = self._extract_with_structured(messages, chunks, paper)
            duration_ms = int((time.monotonic() - t1) * 1000)

            self.trace.record_step(
                job_id=self.job_id,
                agent=self.agent_name,
                tool="extract_claims",
                input_data={"paper_id": paper.id, "chunks_presented": len(chunks)},
                output_data={"claims_extracted": len(claims)},
                duration_ms=duration_ms,
                success=True,
                token_count=usage.get("total_tokens"),
                cost_usd=usage.get("cost_usd"),
            )
            bound_log.info(
                "claims_extracted",
                claims_count=len(claims),
                token_count=usage.get("total_tokens"),
                cost_usd=usage.get("cost_usd"),
                step="extract_claims",
            )
            return claims

    def _extract_with_structured(
        self, messages: list[dict], chunks: list[dict], paper: Paper
    ) -> tuple[list[Claim], dict]:
        try:
            output, usage = self._run_structured(
                ClaimsOutput,
                messages=messages,
                system=SYSTEM_PROMPT,
                max_retries=2,
                phase_tool="extract_claims",
            )
        except Exception as exc:
            logger.warning(
                "extraction_failed",
                arxiv_id=paper.arxiv_id,
                error=str(exc),
                agent=self.agent_name,
                step="extract_claims",
            )
            return [], {}

        claims: list[Claim] = []
        for item in output.claims:
            if item.index < 0 or item.index >= len(chunks):
                logger.warning(
                    "invalid_chunk_index",
                    index=item.index,
                    total_chunks=len(chunks),
                    agent=self.agent_name,
                )
                continue
            chunk = chunks[item.index]
            claims.append(Claim(
                paper_id=paper.id,
                chunk_id=chunk["chunk_id"],
                text=item.text,
                confidence=item.confidence,
                category=item.category,
            ))

        logger.info(
            "valid_claims_mapped",
            valid_claims=len(claims),
            arxiv_id=paper.arxiv_id,
            agent=self.agent_name,
        )
        return claims, usage

    def _fetch_chunks(self, paper: Paper) -> list[dict]:
        queries = [
            f"{paper.title} main contribution findings",
            f"{paper.title} methodology approach",
            f"{paper.title} results evaluation limitations",
        ]

        seen: dict[str, dict] = {}
        for query in queries:
            try:
                result = semantic_search(query=query, paper_ids=[paper.id], n_results=5)
                for chunk in result.get("chunks", []):
                    cid = chunk.get("chunk_id", "")
                    if cid and cid not in seen:
                        seen[cid] = chunk
            except Exception as exc:
                logger.warning(
                    "semantic_search_failed",
                    arxiv_id=paper.arxiv_id,
                    error=str(exc),
                    agent=self.agent_name,
                    step="semantic_search",
                )

        chunks = list(seen.values())[:self.MAX_CHUNKS_PER_PAPER]
        logger.info(
            "chunks_deduped",
            unique_chunks=len(chunks),
            arxiv_id=paper.arxiv_id,
            agent=self.agent_name,
        )
        return chunks
