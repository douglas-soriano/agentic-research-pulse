"""
ExtractAgent — extracts structured claims from a paper.

Python controls chunk_ids entirely:
  1. semantic_search is called in Python (not via tool) to get real chunks.
  2. The LLM is given the chunks by index and asked only to write claim text.
  3. Python maps each index back to the real chunk_id.

This prevents the small-model habit of inventing chunk_ids that do not exist
in ChromaDB, which caused all downstream citation verification to fail.
"""
import json
import logging
import re
import time

from app.agents.base import BaseAgent, LLMCallBudget
from app.models.paper import Paper
from app.models.claim import Claim
from app.tools.vector_tools import semantic_search

logger = logging.getLogger(__name__)

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
        # No tools — Python drives semantic_search directly.
        self.tools = []
        self.tool_map = {}

    def run(self, paper: Paper) -> list[Claim]:
        # Step 1: fetch real chunks from ChromaDB in Python — trace the search.
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

        if not chunks:
            logger.info("ExtractAgent: no chunks found for paper %s (%s)", paper.arxiv_id, paper.title)
            return []

        # Step 2: ask LLM to write claim text only — it never sees chunk_ids.
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
        response = self._run_loop(
            messages,
            system=SYSTEM_PROMPT,
            max_iterations=3,
            force_json_on_completion=True,
        )
        text = self._extract_text(response)
        claims = self._parse_claims(text, chunks, paper)

        self.trace.record_step(
            job_id=self.job_id,
            agent=self.agent_name,
            tool="extract_claims",
            input_data={"paper_id": paper.id, "chunks_presented": len(chunks)},
            output_data={"claims_extracted": len(claims)},
            duration_ms=int((time.monotonic() - t1) * 1000),
            success=True,
        )
        return claims

    # ------------------------------------------------------------------

    def _fetch_chunks(self, paper: Paper) -> list[dict]:
        """Run several semantic queries against this paper's chunks in ChromaDB.
        Returns a deduplicated list capped at MAX_CHUNKS_PER_PAPER."""
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
                logger.warning("ExtractAgent: semantic_search failed for paper %s: %s", paper.arxiv_id, exc)

        chunks = list(seen.values())[:self.MAX_CHUNKS_PER_PAPER]
        logger.debug("ExtractAgent: found %d unique chunks for paper %s", len(chunks), paper.arxiv_id)
        return chunks

    def _parse_claims(self, text: str, chunks: list[dict], paper: Paper) -> list[Claim]:
        text = re.sub(r'^```(?:json)?\s*', '', text.strip())
        text = re.sub(r'\s*```$', '', text).strip()

        data: dict = {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*"claims".*\}', text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        claims: list[Claim] = []
        for c in data.get("claims", []):
            idx = c.get("index")
            claim_text = c.get("text", "").strip()
            if idx is None or not claim_text:
                continue
            if not isinstance(idx, int) or idx < 0 or idx >= len(chunks):
                logger.debug(
                    "ExtractAgent: claim index %s out of range (chunks: %d) — skipped",
                    idx, len(chunks),
                )
                continue
            # chunk_id comes from Python's own search — never from the model.
            chunk = chunks[idx]
            claims.append(
                Claim(
                    paper_id=paper.id,
                    chunk_id=chunk["chunk_id"],
                    text=claim_text,
                    confidence=float(c.get("confidence", 0.8)),
                    category=c.get("category", "finding"),
                )
            )

        logger.info(
            "ExtractAgent: extracted %d valid claims from paper %s",
            len(claims), paper.arxiv_id,
        )
        return claims
