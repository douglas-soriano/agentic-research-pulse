import httpx
import structlog

from app.constants import (
    HTTP_TIMEOUT_SECONDS,
    OPENALEX_ABSTRACT_MAX_CHARS,
    OPENALEX_DEFAULT_MAX_RESULTS,
    OPENALEX_DEFAULT_YEAR,
    OPENALEX_MAX_RESULTS,
)
from app.exceptions import ExternalServiceError
from app.resilience.retry import http_retry

logger = structlog.get_logger(__name__)

OA_SEARCH_URL = "https://api.openalex.org/works"
_SELECT = "id,title,abstract_inverted_index,authorships,publication_year,ids,cited_by_count,doi"
_HEADERS = {"User-Agent": "mailto:researchpulse@example.com"}


def _reconstruct_abstract(inverted_index: dict) -> str:
    if not inverted_index:
        return ""
    words_by_position: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for position in positions:
            words_by_position[position] = word
    return " ".join(words_by_position[position] for position in sorted(words_by_position))


def search_openalex(query: str, max_results: int = OPENALEX_DEFAULT_MAX_RESULTS) -> dict:
    params = {
        "search": query,
        "per-page": min(max_results * 2, OPENALEX_MAX_RESULTS),
        "filter": "has_abstract:true",
        "select": _SELECT,
    }
    try:
        openalex_response = _openalex_request(params)
        openalex_response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            logger.warning("openalex_rate_limited", query=query)
            raise ExternalServiceError("OpenAlex rate limit exceeded") from exc
        raise
    except httpx.HTTPError as exc:
        logger.warning("openalex_request_failed", query=query, error=str(exc))
        raise ExternalServiceError(f"OpenAlex request failed for query {query}") from exc

    payload = openalex_response.json()
    papers = []
    for work in payload.get("results", []):
        identifiers = work.get("ids") or {}

        raw_arxiv = identifiers.get("arxiv", "")
        arxiv_id = raw_arxiv.replace("https://arxiv.org/abs/", "").strip("/")

        if arxiv_id:
            source_url = f"https://arxiv.org/abs/{arxiv_id}"
        else:
            doi = (work.get("doi") or identifiers.get("doi", "")).lstrip("https://doi.org/")
            if not doi:
                continue
            arxiv_id = doi
            source_url = f"https://doi.org/{doi}"

        abstract = _reconstruct_abstract(work.get("abstract_inverted_index") or {})
        authors = [
            (authorship.get("author") or {}).get("display_name", "")
            for authorship in (work.get("authorships") or [])
        ][:3]
        year = work.get("publication_year") or OPENALEX_DEFAULT_YEAR

        papers.append({
            "arxiv_id": arxiv_id,
            "title": (work.get("title") or "").replace("\n", " ").strip(),
            "authors": authors,
            "abstract": abstract[:OPENALEX_ABSTRACT_MAX_CHARS] + ("…" if len(abstract) > OPENALEX_ABSTRACT_MAX_CHARS else ""),
            "published_at": f"{year}-01-01T00:00:00",
            "url": source_url,
            "citation_count": work.get("cited_by_count") or 0,
            "source": "openalex",
        })
        if len(papers) >= max_results:
            break

    return {"papers": papers, "total_found": len(papers)}


@http_retry
def _openalex_request(params: dict) -> httpx.Response:
    return httpx.get(OA_SEARCH_URL, params=params, headers=_HEADERS, timeout=HTTP_TIMEOUT_SECONDS)
