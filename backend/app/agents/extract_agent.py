"""
ExtractAgent — extracts structured claims from a paper using semantic search.
Citation grounding: every claim must reference a chunk_id from the vector DB.
"""
import json

from app.agents.base import BaseAgent
from app.models.paper import Paper
from app.models.claim import Claim
from app.tools.vector_tools import VECTOR_TOOL_MAP, semantic_search_tool
from app.tools.synthesis_tools import SYNTHESIS_TOOL_MAP, extract_claims_tool

SYSTEM_PROMPT = """You are a scientific claim extraction agent.
Given a research paper, your job is to extract the most important claims with
their source references. Every claim MUST be tied to a specific chunk from the vector DB.

Workflow:
1. Call semantic_search to retrieve the most relevant chunks for key aspects of the paper
   (main contribution, methodology, results, limitations).
2. For each important chunk, extract a concise claim (1-2 sentences).
3. Call extract_claims with the paper_id and the list of claims, each with:
   - chunk_id: the exact chunk_id from semantic_search
   - text: the extracted claim
   - category: one of "finding", "method", "limitation", "contribution"
   - confidence: 0.0–1.0

Respond with a JSON object:
{{"claims": [<list of claim dicts>]}}

IMPORTANT: Never invent chunk_ids. Only use chunk_ids returned by semantic_search."""


class ExtractAgent(BaseAgent):
    agent_name = "extract_agent"

    def __init__(self, job_id: str):
        super().__init__(job_id)
        self.tools = [semantic_search_tool, extract_claims_tool]
        self.tool_map = {**VECTOR_TOOL_MAP, **SYNTHESIS_TOOL_MAP}

    def run(self, paper: Paper) -> list[Claim]:
        messages = [
            {
                "role": "user",
                "content": (
                    f"Extract key claims from this paper.\n\n"
                    f"Paper ID: {paper.id}\n"
                    f"arXiv ID: {paper.arxiv_id}\n"
                    f"Title: {paper.title}\n"
                    f"Authors: {', '.join(paper.authors[:3])}\n\n"
                    f"Abstract: {paper.abstract}\n\n"
                    f"Use semantic_search with paper_ids=['{paper.id}'] to retrieve chunks "
                    f"from this specific paper. Extract 3-6 high-quality claims."
                ),
            }
        ]

        response = self._run_loop(messages, system=SYSTEM_PROMPT)
        text = self._extract_text(response)
        return self._parse_claims(text, paper)

    def _parse_claims(self, text: str, paper: Paper) -> list[Claim]:
        import re
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*"claims".*\}', text, re.DOTALL)
            if not match:
                return []
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                return []

        claims = []
        for c in data.get("claims", []):
            if not c.get("chunk_id") or not c.get("text"):
                continue
            claims.append(
                Claim(
                    paper_id=paper.id,
                    chunk_id=c["chunk_id"],
                    text=c["text"],
                    confidence=float(c.get("confidence", 0.8)),
                    category=c.get("category", "finding"),
                )
            )
        return claims
