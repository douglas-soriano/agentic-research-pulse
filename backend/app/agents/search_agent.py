"""
SearchAgent — finds relevant papers for a topic across multiple providers.

Architecture (three-phase, no LLM tool loop):
  Phase 1 — Query planning (1 LLM call):
    The model receives the topic and returns 3 diverse search queries.

  Phase 2 — Multi-provider search (0 LLM calls):
    Queries run in parallel within each provider.
    Providers run sequentially: arXiv → Semantic Scholar → OpenAlex.
    Each provider emits its own trace step so the reasoning timeline shows
    per-provider progress ("Searching arXiv", "Searching Semantic Scholar", etc.)

  Phase 3 — Relevance ranking (0 LLM calls):
    All candidates are merged, deduplicated by arXiv ID, and scored:
      - Position score  : 1 / (rank_in_provider + 1)
      - Citation bonus  : log10(citations + 1) / 5, capped at 0.4
      - Cross-provider  : +0.3 per additional provider that returned the same paper
    Top N by score are returned.
"""
import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from app.agents.base import BaseAgent, LLMCallBudget
from app.config import settings
from app.models.agent_outputs import QueryPlan
from app.tools.arxiv_tools import search_arxiv
from app.tools.openalex_tools import search_openalex

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
- Do NOT use LaTeX, formulas, or special characters other than plain letters and numbers
- If the topic contains an unknown, invented, or nonsensical term (e.g. "ektromos", "zylorbium"), search for THAT EXACT TERM only — do NOT replace it with similar real scientific concepts. Preserve unusual words verbatim in every query."""

# Per-query fetch limit per provider. Larger than max_papers so the ranking
# step has enough candidates to choose from across all three providers.
_FETCH_PER_QUERY = 8

# (provider_fn, trace_tool_name, display_name)
# Semantic Scholar removed — free tier rate limit (100 req/5 min) is too low
# for 3 parallel queries and causes near-constant 429s in practice.
_PROVIDERS: list[tuple[Callable, str, str]] = [
    (search_arxiv,    "arxiv_search",    "arXiv"),
    (search_openalex, "openalex_search", "OpenAlex"),
]


class SearchAgent(BaseAgent):
    agent_name = "search_agent"

    def __init__(self, job_id: str, budget: LLMCallBudget | None = None):
        super().__init__(job_id, budget=budget)
        self.tools = []
        self.tool_map = {}

    def run(self, topic: str, max_papers: int | None = None) -> list[dict]:
        max_papers = max_papers or settings.max_papers_per_topic

        # ── Phase 1: query planning ─────────────────────────────────────────
        t0 = time.monotonic()
        llm_queries = self._plan_queries(topic)

        # Always include the original topic phrase as the first query.
        # Academic search engines index papers by their actual topic name, so
        # the literal phrase often outperforms any paraphrase the LLM generates.
        queries: list[str] = [topic] + [
            q for q in llm_queries if q.lower() != topic.lower()
        ]

        self.trace.record_step(
            job_id=self.job_id,
            agent=self.agent_name,
            tool="plan_queries",
            input_data={"topic": topic},
            output_data={"queries": queries},
            duration_ms=int((time.monotonic() - t0) * 1000),
            success=True,
        )

        # ── Phase 2: parallel provider search ───────────────────────────────
        # Both providers start simultaneously — independent HTTP requests.
        # Trace steps are emitted from the main thread (via as_completed)
        # to stay SQLite-safe.
        all_candidates: list[dict] = []
        provider_counts: dict[str, int] = {}

        def _run_provider(
            provider_fn: Callable, tool_name: str, display_name: str
        ) -> tuple[str, str, list[dict], dict[str, int], int]:
            t = time.monotonic()
            papers, per_query = self._search_provider_queries(
                provider_fn, queries, _FETCH_PER_QUERY
            )
            return tool_name, display_name, papers, per_query, int((time.monotonic() - t) * 1000)

        with ThreadPoolExecutor(max_workers=len(_PROVIDERS)) as pool:
            futures = {
                pool.submit(_run_provider, fn, tn, dn): tn
                for fn, tn, dn in _PROVIDERS
            }
            for future in as_completed(futures):
                tool_name, display_name, papers, per_query, ms = future.result()
                all_candidates.extend(papers)
                provider_counts[display_name] = len(papers)
                self.trace.record_step(
                    job_id=self.job_id,
                    agent=self.agent_name,
                    tool=tool_name,
                    input_data={"queries": queries, "n_per_query": _FETCH_PER_QUERY},
                    output_data={
                        "papers_found": len(papers),
                        "per_query": per_query,
                        "provider": display_name,
                    },
                    duration_ms=ms,
                    success=True,
                )
                logger.info(
                    "SearchAgent: %s returned %d papers for topic %r",
                    display_name, len(papers), topic,
                )

        # ── Phase 3: dedup + relevance ranking ──────────────────────────────
        t2 = time.monotonic()
        unique_ids = len({
            re.sub(r'v\d+$', '', p.get("arxiv_id", ""))
            for p in all_candidates if p.get("arxiv_id")
        })
        selected = self._rank_and_select(all_candidates, max_papers)

        # Count papers confirmed by more than one provider (cross-provider signal).
        cross_provider = 0
        if selected:
            aid_occurrences: dict[str, int] = {}
            for p in all_candidates:
                aid = re.sub(r'v\d+$', '', p.get("arxiv_id", ""))
                if aid:
                    aid_occurrences[aid] = aid_occurrences.get(aid, 0) + 1
            cross_provider = sum(
                1 for p in selected
                if aid_occurrences.get(re.sub(r'v\d+$', '', p.get("arxiv_id", "")), 1) > 1
            )

        self.trace.record_step(
            job_id=self.job_id,
            agent=self.agent_name,
            tool="rank_papers",
            input_data={
                "total_candidates": unique_ids,
                "providers": list(provider_counts.keys()),
            },
            output_data={
                "selected": len(selected),
                "candidates": unique_ids,
                "cross_provider_matches": cross_provider,
                **{f"{k.lower().replace(' ', '_')}_papers": v
                   for k, v in provider_counts.items()},
            },
            duration_ms=int((time.monotonic() - t2) * 1000),
            success=True,
        )

        # Relevance gate — discard results when the providers returned unrelated papers.
        if selected and not self._papers_are_relevant(topic, selected):
            selected = []

        if not selected:
            logger.warning("SearchAgent: no papers found for topic %r", topic)
        else:
            logger.info(
                "SearchAgent: selected %d from %d unique candidates for topic %r",
                len(selected), unique_ids, topic,
            )

        return selected

    # ------------------------------------------------------------------
    # Phase 1 — query planning
    # ------------------------------------------------------------------

    def _plan_queries(self, topic: str) -> list[str]:
        try:
            result: QueryPlan = self._run_structured(
                QueryPlan,
                messages=[{
                    "role": "user",
                    "content": f"Topic: {topic}\n\nGenerate 3 diverse arXiv search queries. Return JSON only.",
                }],
                system=QUERY_SYSTEM,
                max_retries=2,
                phase_tool="plan_queries",
            )
            return result.queries
        except Exception as exc:
            logger.warning(
                "SearchAgent: structured query plan failed for %r (%s) — topic-only fallback",
                topic, exc,
            )
            return [topic]

    # ------------------------------------------------------------------
    # Phase 2 — per-provider parallel search
    # ------------------------------------------------------------------

    def _search_provider_queries(
        self,
        provider_fn: Callable,
        queries: list[str],
        n_per_query: int,
    ) -> tuple[list[dict], dict[str, int]]:
        """Run all queries against one provider in parallel."""
        all_papers: list[dict] = []
        per_query: dict[str, int] = {}

        def run_one(query: str) -> tuple[str, list[dict]]:
            try:
                result = provider_fn(query=query, max_results=n_per_query)
                papers = result.get("papers", [])
                for rank, p in enumerate(papers):
                    p["_rank"] = rank
                return query, papers
            except Exception as exc:
                logger.warning(
                    "SearchAgent: %s failed for query %r: %s",
                    provider_fn.__name__, query, exc,
                )
                return query, []

        with ThreadPoolExecutor(max_workers=len(queries)) as pool:
            futures = {pool.submit(run_one, q): q for q in queries}
            for future in as_completed(futures):
                query, papers = future.result()
                per_query[query] = len(papers)
                all_papers.extend(papers)

        return all_papers, per_query

    # ------------------------------------------------------------------
    # Phase 3 — relevance ranking
    # ------------------------------------------------------------------

    def _rank_and_select(self, candidates: list[dict], limit: int) -> list[dict]:
        """
        Dedup by arXiv ID and score each paper:
          position_score = 1 / (rank_in_provider + 1)
          citation_bonus = min(log10(citations + 1) / 5, 0.4)
          cross_provider = +0.3 per additional provider that returned the same paper

        Returns top `limit` papers sorted by score descending.
        """
        seen: dict[str, dict] = {}

        for paper in candidates:
            aid = re.sub(r'v\d+$', '', paper.get("arxiv_id", ""))
            if not aid:
                continue

            rank = paper.get("_rank", 10)
            position_score = 1.0 / (rank + 1)
            citations = paper.get("citation_count") or 0
            citation_bonus = min(math.log10(citations + 1) / 5.0, 0.4)
            score = position_score + citation_bonus

            if aid in seen:
                seen[aid]["_score"] += score + 0.3  # cross-provider boost
            else:
                clean = {k: v for k, v in paper.items() if not k.startswith("_")}
                clean["arxiv_id"] = aid
                clean["_score"] = score
                seen[aid] = clean

        ranked = sorted(seen.values(), key=lambda p: p["_score"], reverse=True)
        return [{k: v for k, v in p.items() if k != "_score"} for p in ranked[:limit]]

    # ------------------------------------------------------------------
    # Relevance gate (unchanged)
    # ------------------------------------------------------------------

    @staticmethod
    def _papers_are_relevant(topic: str, papers_meta: list[dict]) -> bool:
        import re as _re

        _STOPWORDS = {
            "for", "in", "of", "the", "a", "an", "and", "or", "with",
            "on", "at", "to", "is", "are", "by", "from", "using", "via",
            "based", "approach", "method", "methods", "new", "novel",
        }

        raw_tokens = _re.findall(r"[A-Za-z0-9]+", topic)
        significant: list[str] = []
        for tok in raw_tokens:
            low = tok.lower()
            if low in _STOPWORDS:
                continue
            # Only flag tokens that are clearly unusual: contain a digit ("asdijon3")
            # or are long enough to be domain-specific (≥7 chars, like "ektromos").
            # Common acronyms (GPT, LLM, RAG, BERT…) are intentionally excluded —
            # papers often describe the same concept with different terminology.
            if any(c.isdigit() for c in tok) or len(tok) >= 7:
                significant.append(low)

        if not significant:
            return True

        for paper in papers_meta:
            corpus = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()
            if any(tok in corpus for tok in significant):
                return True

        logger.warning(
            "SearchAgent: none of the significant tokens %s appear in any "
            "returned paper — treating search as no results for topic %r",
            significant, topic,
        )
        return False
