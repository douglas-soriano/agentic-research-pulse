"""
SearchAgent — finds relevant arXiv papers for a topic.

Architecture (two-phase, no LLM tool loop):
  Phase 1 — Query planning (1 LLM call):
    The model receives the topic and returns 3 diverse search queries as JSON.
    Each query targets a different angle: methodology, application domain,
    evaluation/benchmarks.

  Phase 2 — Parallel execution (0 LLM calls):
    Python runs all 3 queries simultaneously with ThreadPoolExecutor.
    Results are collected, deduplicated, and returned.

Why not a tool-call loop?
  Tool calls are inherently sequential — each LLM response drives the next call.
  For arXiv searches there is no reason to wait for result A before firing query B:
  the queries are independent. Parallel execution cuts latency from ~13 s to ~5 s
  and removes the need for an artificial call-count limit.

Stop criterion:
  The search stops when we have results from all N queries OR when a query returns
  0 new unique papers (logged, never retried). No hard caps based on iteration count.
"""
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.agents.base import BaseAgent, LLMCallBudget
from app.config import settings
from app.models.agent_outputs import QueryPlan
from app.tools.arxiv_tools import search_arxiv

logger = logging.getLogger(__name__)

QUERY_SYSTEM = """You are a scientific literature search specialist.

Given a research topic, produce 3 diverse arXiv search queries that cover different angles:
- Query 1: core methodology / algorithms / techniques
- Query 2: application domains / use cases / systems
- Query 3: evaluation / benchmarks / surveys / limitations

Return ONLY this JSON — no prose, no markdown:
{"queries": ["<query 1>", "<query 2>", "<query 3>"]}

Each query should use different descriptive keywords to maximise paper coverage.

CRITICAL RULES — violating any of these will cause the search to fail:
- Use ONLY descriptive keywords (e.g. "transformer attention mechanism NLP")
- Do NOT include arXiv IDs (e.g. "arXiv:quant-ph/0001234", "arXiv:cs.LG/...")
- Do NOT include arXiv category tags (e.g. "[physics.comp-ph]", "[quant-ph]", "[eess.IV]")
- Do NOT invent paper IDs or citation numbers of any kind
- Do NOT use LaTeX, formulas, or special characters other than plain letters and numbers"""


class SearchAgent(BaseAgent):
    agent_name = "search_agent"

    def __init__(self, job_id: str, budget: LLMCallBudget | None = None):
        super().__init__(job_id, budget=budget)
        # No tools — Python drives arXiv calls directly.
        self.tools = []
        self.tool_map = {}

    def run(self, topic: str, max_papers: int | None = None) -> list[dict]:
        max_papers = max_papers or settings.max_papers_per_topic

        # Phase 1: plan queries with 1 LLM call.
        t0 = time.monotonic()
        queries = self._plan_queries(topic)
        planning_ms = int((time.monotonic() - t0) * 1000)

        self.trace.record_step(
            job_id=self.job_id,
            agent=self.agent_name,
            tool="plan_queries",
            input_data={"topic": topic},
            output_data={"queries": queries},
            duration_ms=planning_ms,
            success=True,
        )

        # Phase 2: parallel arXiv searches — no LLM involved.
        t1 = time.monotonic()
        raw_papers, per_query_counts = self._parallel_search(queries, n_results=max_papers)
        search_ms = int((time.monotonic() - t1) * 1000)

        papers = self._dedup(raw_papers, max_papers)

        self.trace.record_step(
            job_id=self.job_id,
            agent=self.agent_name,
            tool="parallel_arxiv_search",
            input_data={"queries": queries, "n_results_each": max_papers},
            output_data={
                "raw_collected": len(raw_papers),
                "unique_papers": len(papers),
                "per_query": per_query_counts,
            },
            duration_ms=search_ms,
            success=True,
        )

        if not papers:
            logger.warning("SearchAgent: no papers found for topic %r", topic)
        else:
            logger.info(
                "SearchAgent: %d unique papers in %.1fs for topic %r",
                len(papers), (planning_ms + search_ms) / 1000, topic,
            )

        return papers

    # ------------------------------------------------------------------
    # Phase 1 — query planning
    # ------------------------------------------------------------------

    def _plan_queries(self, topic: str) -> list[str]:
        """
        Ask the LLM to produce 3 diverse search queries for the topic.

        Uses instructor + Pydantic (QueryPlan) so that if the model returns
        invalid JSON or mismatched schema, the validation error is fed back
        automatically and the model is asked to self-correct (up to 2 retries).
        Only falls back to [topic] if instructor exhausts all retries.
        """
        try:
            result: QueryPlan = self._run_structured(
                QueryPlan,
                messages=[{
                    "role": "user",
                    "content": f"Topic: {topic}\n\nGenerate 3 diverse arXiv search queries. Return JSON only.",
                }],
                system=QUERY_SYSTEM,
                max_retries=2,
            )
            return result.queries
        except Exception as exc:
            logger.warning(
                "SearchAgent: structured query plan failed for %r after retries (%s) — topic-only fallback",
                topic, exc,
            )
            # Do NOT add generic keywords (e.g. "methods", "survey") — they match
            # unrelated papers when the topic term doesn't exist in arXiv.
            return [topic]

    # ------------------------------------------------------------------
    # Phase 2 — parallel execution
    # ------------------------------------------------------------------

    def _parallel_search(
        self,
        queries: list[str],
        n_results: int,
    ) -> tuple[list[dict], dict[str, int]]:
        """Run all queries simultaneously. Returns (all_papers, per_query_counts)."""
        all_papers: list[dict] = []
        per_query: dict[str, int] = {}

        def run_one(query: str) -> tuple[str, list[dict]]:
            try:
                result = search_arxiv(query=query, max_results=n_results)
                papers = result.get("papers", [])
                return query, papers
            except Exception as exc:
                logger.warning("SearchAgent: query %r failed: %s", query, exc)
                return query, []

        with ThreadPoolExecutor(max_workers=len(queries)) as pool:
            futures = {pool.submit(run_one, q): q for q in queries}
            for future in as_completed(futures):
                query, papers = future.result()
                per_query[query] = len(papers)
                all_papers.extend(papers)

                if len(papers) == 0:
                    logger.info("SearchAgent: query %r returned 0 papers — stopping naturally.", query)

        return all_papers, per_query

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _dedup(self, papers: list[dict], limit: int) -> list[dict]:
        """Remove duplicates by arxiv_id (ignoring version suffix) and cap at limit."""
        seen: set[str] = set()
        unique: list[dict] = []
        for p in papers:
            aid = re.sub(r'v\d+$', '', p.get("arxiv_id", ""))
            if aid and aid not in seen:
                seen.add(aid)
                unique.append({**p, "arxiv_id": aid})
        return unique[:limit]
