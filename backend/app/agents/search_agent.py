"""
SearchAgent — finds relevant arXiv papers for a topic.

Query decomposition: the agent is instructed to plan exactly 3 sub-queries
covering different angles of the topic, execute search_arxiv for each,
then merge and deduplicate results by arxiv_id before returning.
"""
import json
import logging
import re

from app.agents.base import BaseAgent, LLMCallBudget
from app.config import settings
from app.tools.arxiv_tools import ARXIV_TOOL_MAP, search_arxiv_tool, fetch_paper_tool

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a scientific literature search agent.

Your job is to find the most relevant recent arXiv papers on a given topic.

You MUST follow this exact workflow:

STEP 1 — Query planning:
Think about 3 different angles or sub-aspects of the topic that would each yield
distinct papers (e.g. methodology, application domain, evaluation approach).
Write out your 3 planned queries briefly before calling any tools.

STEP 2 — Execute all 3 searches:
Call search_arxiv exactly 3 times, once per sub-query.
Use different wording each time to maximise coverage.

STEP 3 — Merge and deduplicate:
Collect all results across all 3 searches.
Remove duplicate papers (same arxiv_id).
Keep at most {max_papers} papers, prioritising relevance and recency.

STEP 4 — Return results:
Respond with a JSON object and nothing else:
{{"papers": [<deduplicated paper dicts>]}}

Each paper dict must preserve all fields from search_arxiv results:
arxiv_id, title, authors, abstract, published_at, url."""


class SearchAgent(BaseAgent):
    agent_name = "search_agent"

    def __init__(self, job_id: str, budget: LLMCallBudget | None = None):
        super().__init__(job_id, budget=budget)
        self.tools = [search_arxiv_tool, fetch_paper_tool]
        self.tool_map = ARXIV_TOOL_MAP

    def run(self, topic: str, max_papers: int | None = None) -> list[dict]:
        max_papers = max_papers or settings.max_papers_per_topic
        system = SYSTEM_PROMPT.format(max_papers=max_papers)
        messages = [
            {
                "role": "user",
                "content": (
                    f"Find {max_papers} high-quality recent arXiv papers about: {topic}\n\n"
                    f"Remember: plan 3 sub-queries, execute all 3 searches, "
                    f"then deduplicate and return JSON."
                ),
            }
        ]

        # force_tool_first=True prevents Gemini from answering with plain text
        # on the first turn instead of actually calling search_arxiv.
        # force_json_on_completion=True catches the case where Gemini returns
        # a prose summary ("STEP 1 — planning...") instead of the required JSON.
        response = self._run_loop(
            messages, system=system,
            force_tool_first=True,
            force_json_on_completion=True,
        )
        text = self._extract_text(response)
        papers = self._parse_and_dedup(text)
        if not papers:
            logger.warning(
                "SearchAgent: _parse_and_dedup returned 0 papers. "
                "Raw model text (first 500 chars): %r", text[:500]
            )
        return papers

    def _parse_and_dedup(self, text: str) -> list[dict]:
        papers = self._extract_json_papers(text)

        # Deduplicate by arxiv_id (agent should do this but we enforce it)
        seen: set[str] = set()
        unique = []
        for p in papers:
            aid = p.get("arxiv_id", "")
            if aid and aid not in seen:
                seen.add(aid)
                unique.append(p)
        return unique

    def _extract_json_papers(self, text: str) -> list[dict]:
        text = _strip_markdown(text)
        try:
            return json.loads(text).get("papers", [])
        except (json.JSONDecodeError, AttributeError):
            pass
        match = re.search(r'\{.*?"papers".*?\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group()).get("papers", [])
            except json.JSONDecodeError:
                pass
        return []


def _strip_markdown(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` wrappers that models sometimes add."""
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return text.strip()
