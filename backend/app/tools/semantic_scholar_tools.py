import httpx
import structlog

from app.constants import (
    HTTP_TIMEOUT_SECONDS,
    SEMANTIC_SCHOLAR_ABSTRACT_MAX_CHARS,
    SEMANTIC_SCHOLAR_DEFAULT_MAX_RESULTS,
    SEMANTIC_SCHOLAR_DEFAULT_YEAR,
    SEMANTIC_SCHOLAR_MAX_RESULTS,
)
from app.exceptions import ExternalServiceError
from app.resilience.retry import http_retry

logger = structlog.get_logger(__name__)

SEMANTIC_SCHOLAR_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = "title,abstract,authors,year,externalIds,citationCount,url,publicationDate"


def search_semantic_scholar(
    query: str,
    max_results: int = SEMANTIC_SCHOLAR_DEFAULT_MAX_RESULTS,
) -> dict:
    params = {
        "query": query,
        "limit": min(max_results, SEMANTIC_SCHOLAR_MAX_RESULTS),
        "fields": _FIELDS,
    }
    try:
        semantic_scholar_response = _semantic_scholar_request(params)
        semantic_scholar_response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            logger.warning("semantic_scholar_rate_limited", query=query)
            raise ExternalServiceError("Semantic Scholar rate limit exceeded") from exc
        raise
    except httpx.HTTPError as exc:
        logger.warning("semantic_scholar_request_failed", query=query, error=str(exc))
        raise ExternalServiceError(f"Semantic Scholar request failed for query {query}") from exc

    payload = semantic_scholar_response.json()
    papers = []
    for paper in payload.get("data", []):
        identifiers = paper.get("externalIds") or {}
        arxiv_id = identifiers.get("ArXiv", "")
        doi = identifiers.get("DOI", "")
        if arxiv_id:
            source_url = f"https://arxiv.org/abs/{arxiv_id}"
        elif doi:
            arxiv_id = doi
            source_url = f"https://doi.org/{doi}"
        else:
            continue

        abstract = (paper.get("abstract") or "").replace("\n", " ").strip()
        authors = [
            author.get("name", "")
            for author in (paper.get("authors") or [])
            if author.get("name")
        ][:3]
        year = paper.get("year") or SEMANTIC_SCHOLAR_DEFAULT_YEAR
        published_at = paper.get("publicationDate") or f"{year}-01-01"

        papers.append({
            "arxiv_id": arxiv_id,
            "title": (paper.get("title") or "").replace("\n", " ").strip(),
            "authors": authors,
            "abstract": abstract[:SEMANTIC_SCHOLAR_ABSTRACT_MAX_CHARS] + ("…" if len(abstract) > SEMANTIC_SCHOLAR_ABSTRACT_MAX_CHARS else ""),
            "published_at": f"{published_at}T00:00:00",
            "url": source_url,
            "citation_count": paper.get("citationCount") or 0,
            "source": "semantic_scholar",
        })
        if len(papers) >= max_results:
            break

    return {"papers": papers, "total_found": len(papers)}


@http_retry
def _semantic_scholar_request(params: dict) -> httpx.Response:
    return httpx.get(SEMANTIC_SCHOLAR_SEARCH_URL, params=params, timeout=HTTP_TIMEOUT_SECONDS)
