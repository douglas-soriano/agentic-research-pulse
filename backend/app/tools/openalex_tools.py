"""
OpenAlex search tool.
Fully open, no API key. Polite pool: include email in User-Agent.
All HTTP calls use tenacity retry (1s→2s→4s, up to 3 retries).

ID strategy:
  - Papers with an arXiv preprint  → arxiv_id = arXiv ID
  - Papers without arXiv (journals) → arxiv_id = DOI
"""
import httpx
import structlog

from app.resilience.retry import http_retry

logger = structlog.get_logger(__name__)

OA_SEARCH_URL = "https://api.openalex.org/works"
_SELECT = "id,title,abstract_inverted_index,authorships,publication_year,ids,cited_by_count,doi"
_HEADERS = {"User-Agent": "mailto:researchpulse@example.com"}


def _reconstruct_abstract(inverted: dict) -> str:
    if not inverted:
        return ""
    pos_map: dict[int, str] = {}
    for word, positions in inverted.items():
        for pos in positions:
            pos_map[pos] = word
    return " ".join(pos_map[i] for i in sorted(pos_map))


def search_openalex(query: str, max_results: int = 8) -> dict:
    """Search OpenAlex. Returns arXiv papers with arXiv IDs and non-arXiv papers with DOIs."""
    params = {
        "search": query,
        "per-page": min(max_results * 2, 50),
        "filter": "has_abstract:true",
        "select": _SELECT,
    }
    try:
        response = _openalex_request(params)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            logger.warning("openalex_rate_limited", query=query)
            return {"papers": [], "total_found": 0, "error": "rate_limited"}
        raise
    except Exception as exc:
        logger.warning("openalex_request_failed", query=query, error=str(exc))
        return {"papers": [], "total_found": 0, "error": str(exc)}

    data = response.json()
    papers = []
    for item in data.get("results", []):
        ids = item.get("ids") or {}

        raw_arxiv = ids.get("arxiv", "")
        arxiv_id = raw_arxiv.replace("https://arxiv.org/abs/", "").strip("/")

        if arxiv_id:
            source_url = f"https://arxiv.org/abs/{arxiv_id}"
        else:
            doi = (item.get("doi") or ids.get("doi", "")).lstrip("https://doi.org/")
            if not doi:
                continue
            arxiv_id = doi
            source_url = f"https://doi.org/{doi}"

        abstract = _reconstruct_abstract(item.get("abstract_inverted_index") or {})
        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in (item.get("authorships") or [])
        ][:3]
        year = item.get("publication_year") or 2000

        papers.append({
            "arxiv_id": arxiv_id,
            "title": (item.get("title") or "").replace("\n", " ").strip(),
            "authors": authors,
            "abstract": abstract[:400] + ("…" if len(abstract) > 400 else ""),
            "published_at": f"{year}-01-01T00:00:00",
            "url": source_url,
            "citation_count": item.get("cited_by_count") or 0,
            "source": "openalex",
        })
        if len(papers) >= max_results:
            break

    return {"papers": papers, "total_found": len(papers)}


@http_retry
def _openalex_request(params: dict) -> httpx.Response:
    return httpx.get(OA_SEARCH_URL, params=params, headers=_HEADERS, timeout=20)
