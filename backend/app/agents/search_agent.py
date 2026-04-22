"""
SearchAgent — finds relevant arXiv papers for a topic.

Papers are collected directly from search_arxiv tool call results (not from the
model's final text), so truncated LLM responses never cause 0-paper failures.
"""
import logging
import re

from app.agents.base import BaseAgent, LLMCallBudget
from app.config import settings
from app.tools.arxiv_tools import search_arxiv_tool, search_arxiv

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a scientific literature search agent.

Your job is to find the most relevant recent arXiv papers on a given topic.

You MUST follow this exact workflow:

STEP 1 — Query planning:
Think about 3 different angles or sub-aspects of the topic that would each yield
distinct papers (e.g. methodology, application domain, evaluation approach).

STEP 2 — Execute all 3 searches:
Call search_arxiv exactly 3 times, once per sub-query.
Use different wording each time to maximise coverage.

STEP 3 — Done:
After calling search_arxiv 3 times, reply with a single word: DONE"""


class SearchAgent(BaseAgent):
    agent_name = "search_agent"

    def __init__(self, job_id: str, budget: LLMCallBudget | None = None):
        super().__init__(job_id, budget=budget)
        self._search_calls = 0
        self._collected_papers: list[dict] = []
        self.tools = [search_arxiv_tool]
        self.tool_map = {"search_arxiv": self._guarded_search}

    def _guarded_search(self, query: str, max_results: int = 5) -> dict:
        self._search_calls += 1
        if self._search_calls > 3:
            return {
                "papers": [],
                "total_found": 0,
                "note": "Search quota reached (3 calls used). Reply DONE now.",
            }
        result = search_arxiv(query=query, max_results=max_results)
        # Collect directly — don't rely on model re-serializing all papers.
        self._collected_papers.extend(result.get("papers", []))
        return result

    def run(self, topic: str, max_papers: int | None = None) -> list[dict]:
        max_papers = max_papers or settings.max_papers_per_topic
        self._search_calls = 0
        self._collected_papers = []

        messages = [
            {
                "role": "user",
                "content": (
                    f"Find up to {max_papers} high-quality recent arXiv papers about: {topic}\n\n"
                    f"Plan 3 sub-queries, execute all 3 searches, then reply DONE."
                ),
            }
        ]

        self._run_loop(
            messages, system=SYSTEM_PROMPT,
            max_iterations=8,
            force_tool_first=True,
        )

        papers = self._dedup(self._collected_papers, max_papers)
        if not papers:
            logger.warning("SearchAgent found no papers for topic: %r", topic)
        else:
            logger.info("SearchAgent collected %d unique papers for topic: %r", len(papers), topic)
        return papers

    def _dedup(self, papers: list[dict], limit: int) -> list[dict]:
        seen: set[str] = set()
        unique: list[dict] = []
        for p in papers:
            # Normalise version suffix: "2312.00001v3" → "2312.00001"
            aid = re.sub(r'v\d+$', '', p.get("arxiv_id", ""))
            if aid and aid not in seen:
                seen.add(aid)
                p = {**p, "arxiv_id": aid}  # store without version suffix
                unique.append(p)
        return unique[:limit]
