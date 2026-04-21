"""
SynthesisAgent — synthesizes a living review from verified claims.

Citation format:
  Inline tokens:  [citation_0001], [citation_0002], …
  Returned map:   {"0001": {paper_id, arxiv_id, title, authors, chunk_id}, …}

Citation grounding is enforced: verify_citation must return True before
a token is assigned. Rejected citations are counted and excluded.
The synthesis text is stored verbatim; the API returns both text + map.
"""
import json
import re

from app.agents.base import BaseAgent, LLMCallBudget
from app.models.claim import Claim
from app.models.paper import Paper
from app.models.review import CitedPaper
from app.tools.synthesis_tools import SYNTHESIS_TOOL_MAP, verify_citation_tool
from app.tools.vector_tools import VECTOR_TOOL_MAP, semantic_search_tool

SYSTEM_PROMPT = """You are a scientific synthesis agent producing a living literature review.

Citation token format: [citation_XXXX] where XXXX is a zero-padded 4-digit counter (0001, 0002, …).

REQUIRED WORKFLOW:

1. For EVERY claim you intend to cite, call verify_citation(chunk_id, paper_id).
   - verified=True  → assign the next [citation_XXXX] token to this claim
   - verified=False → discard entirely; never include it

2. Write a synthesis (4–6 paragraphs) covering main themes, key findings,
   methodological patterns, and open problems.
   Use [citation_XXXX] tokens inline — never bare arxiv IDs or titles.

3. Respond with ONLY this JSON (no surrounding prose):
{
  "synthesis": "<text with [citation_XXXX] tokens inline>",
  "citations": {
    "0001": {"paper_id": "...", "arxiv_id": "...", "title": "...", "authors": [...], "chunk_id": "..."},
    "0002": { ... }
  },
  "rejected_count": <integer>
}

RULES:
- Every token that appears in "synthesis" MUST have an entry in "citations".
- "citations" must contain ONLY tokens with verify_citation → verified=True.
- Tokens are assigned sequentially in the order you first verify them.
- Do not reuse a token for two different claims."""


class SynthesisAgent(BaseAgent):
    agent_name = "synthesis_agent"

    def __init__(self, job_id: str, budget: LLMCallBudget | None = None):
        super().__init__(job_id, budget=budget)
        self.tools = [verify_citation_tool, semantic_search_tool]
        self.tool_map = {**SYNTHESIS_TOOL_MAP, **VECTOR_TOOL_MAP}

    def run(
        self,
        topic: str,
        claims: list[Claim],
        papers: list[Paper],
    ) -> dict:
        """
        Returns:
          synthesis          str   — text with [citation_XXXX] tokens
          citations          dict  — {"XXXX": {paper_id, arxiv_id, title, authors, chunk_id}}
          cited_papers       list  — CitedPaper objects (for backward-compat DB storage)
          citations_verified int
          citations_rejected int
        """
        claims_payload = [
            {
                "paper_id": c.paper_id,
                "chunk_id": c.chunk_id,
                "text": c.text,
                "category": c.category,
                "confidence": c.confidence,
            }
            for c in claims
        ]
        papers_payload = [
            {"paper_id": p.id, "arxiv_id": p.arxiv_id, "title": p.title, "authors": p.authors[:3]}
            for p in papers
        ]

        messages = [
            {
                "role": "user",
                "content": (
                    f"Synthesize a living review for the topic: '{topic}'\n\n"
                    f"Papers:\n{json.dumps(papers_payload, indent=2)}\n\n"
                    f"Claims ({len(claims)} total):\n{json.dumps(claims_payload, indent=2)}\n\n"
                    f"Call verify_citation for every claim before citing it. "
                    f"Use [citation_XXXX] tokens for verified citations."
                ),
            }
        ]

        response = self._run_loop(messages, system=SYSTEM_PROMPT, max_iterations=30)
        text = self._extract_text(response)
        return self._parse_result(text, claims, papers)

    # ------------------------------------------------------------------

    def _parse_result(self, text: str, claims: list[Claim], papers: list[Paper]) -> dict:
        text = re.sub(r'^```(?:json)?\s*', '', text.strip())
        text = re.sub(r'\s*```$', '', text).strip()
        data = {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*?"synthesis".*?\}', text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        synthesis = data.get("synthesis", text)
        citations: dict[str, dict] = data.get("citations", {})
        rejected_count: int = data.get("rejected_count", 0)

        # Normalise: ensure only tokens that actually appear in the text are kept
        citations = {
            k: v for k, v in citations.items()
            if f"[citation_{k}]" in synthesis
        }

        cited_papers = self._build_cited_papers(citations, papers)

        return {
            "synthesis": synthesis,
            "citations": citations,
            "cited_papers": cited_papers,
            "citations_verified": len(citations),
            "citations_rejected": rejected_count,
        }

    def _build_cited_papers(
        self,
        citations: dict[str, dict],
        papers: list[Paper],
    ) -> list[CitedPaper]:
        paper_map = {p.id: p for p in papers}
        # Group chunk_ids by paper_id from the citations map
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
