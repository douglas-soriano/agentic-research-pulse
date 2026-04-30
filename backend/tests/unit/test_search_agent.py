from __future__ import annotations

import threading
import time
from contextlib import nullcontext

from app.agents import search_agent as search_agent_module
from app.agents.search_agent import SearchAgent


class TraceRecorder:
    def __init__(self):
        self.steps = []

    def record_step(self, **kwargs):
        self.steps.append(kwargs)


def test_search_agent_runs_all_providers_in_parallel(monkeypatch):
    started: dict[str, float] = {}
    lock = threading.Lock()
    condition = threading.Condition(lock)

    def make_provider(name: str):
        def provider(query: str, max_results: int) -> dict:
            with condition:
                started.setdefault(name, time.monotonic())
                condition.notify_all()
                condition.wait_for(lambda: len(started) == 3, timeout=0.5)
            return {
                "papers": [
                    {
                        "arxiv_id": f"{name}-{query}",
                        "title": f"{name} paper",
                        "authors": [name],
                        "abstract": "retrieval augmented generation",
                        "published_at": "2024-01-01T00:00:00",
                        "url": f"https://example.com/{name}",
                        "citation_count": 1,
                    }
                ],
                "total_found": 1,
            }

        provider.__name__ = f"search_{name}"
        return provider

    providers = [
        (make_provider("arxiv"), "arxiv_search", "arXiv"),
        (make_provider("openalex"), "openalex_search", "OpenAlex"),
        (make_provider("semantic"), "semantic_scholar_search", "Semantic Scholar"),
    ]
    monkeypatch.setattr(search_agent_module, "_PROVIDERS", providers)
    monkeypatch.setattr(search_agent_module, "agent_trace", lambda *args, **kwargs: nullcontext())

    agent = SearchAgent.__new__(SearchAgent)
    agent.job_id = "job-1"
    agent.trace = TraceRecorder()
    agent.agent_name = "search_agent"
    agent._plan_queries = lambda topic: ["query-a", "query-b"]

    selected = agent.run("retrieval augmented generation", max_papers=2)

    assert set(started) == {"arxiv", "openalex", "semantic"}
    assert max(started.values()) - min(started.values()) < 0.2
    assert len(selected) == 2

    provider_steps = [
        step for step in agent.trace.steps
        if step["tool"] in {"arxiv_search", "openalex_search", "semantic_scholar_search"}
    ]
    assert [step["tool"] for step in provider_steps] == [
        "arxiv_search",
        "openalex_search",
        "semantic_scholar_search",
    ]

    rank_step = next(step for step in agent.trace.steps if step["tool"] == "rank_papers")
    assert rank_step["input_data"]["providers"] == ["arXiv", "OpenAlex", "Semantic Scholar"]


def test_search_agent_cross_provider_count_uses_distinct_sources():
    candidates = [
        {
            "arxiv_id": "paper-1",
            "title": "Paper 1",
            "authors": [],
            "abstract": "retrieval augmented generation",
            "source": "arxiv",
            "_rank": 0,
        },
        {
            "arxiv_id": "paper-1",
            "title": "Paper 1 duplicate query",
            "authors": [],
            "abstract": "retrieval augmented generation",
            "source": "arxiv",
            "_rank": 1,
        },
        {
            "arxiv_id": "paper-2",
            "title": "Paper 2",
            "authors": [],
            "abstract": "retrieval augmented generation",
            "source": "arxiv",
            "_rank": 0,
        },
        {
            "arxiv_id": "paper-2",
            "title": "Paper 2 OpenAlex",
            "authors": [],
            "abstract": "retrieval augmented generation",
            "source": "openalex",
            "_rank": 0,
        },
    ]
    selected = SearchAgent._rank_and_select(SearchAgent.__new__(SearchAgent), candidates, 2)
    sources_by_paper = {}
    for paper in candidates:
        sources_by_paper.setdefault(paper["arxiv_id"], set()).add(paper["source"])

    cross_provider = sum(
        1 for paper in selected
        if len(sources_by_paper.get(paper["arxiv_id"], set())) > 1
    )

    assert cross_provider == 1
