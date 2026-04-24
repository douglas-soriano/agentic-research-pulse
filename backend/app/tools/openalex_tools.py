"""
OpenAlex search tool.
Fully open, no API key. Polite pool: include email in User-Agent.

ID strategy:
  - Papers with an arXiv preprint  → arxiv_id = arXiv ID, source_url = arxiv.org URL
  - Papers without arXiv (journals, etc.) → arxiv_id = DOI, source_url = doi.org URL
  PaperService detects DOI-based IDs (start with "10.") and skips the arXiv
  full-text fetch, falling back to the abstract for embedding.

Abstract note: OpenAlex stores abstracts as an inverted index
  {"word": [pos1, pos2, ...], ...}
which is reconstructed to plain text before returning.
"""
import httpx

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
        response = httpx.get(OA_SEARCH_URL, params=params, headers=_HEADERS, timeout=20)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            return {"papers": [], "total_found": 0, "error": "rate_limited"}
        raise

    data = response.json()
    papers = []
    for item in data.get("results", []):
        ids = item.get("ids") or {}

        # Prefer arXiv ID — enables full-text fetch later.
        raw_arxiv = ids.get("arxiv", "")
        arxiv_id = raw_arxiv.replace("https://arxiv.org/abs/", "").strip("/")

        if arxiv_id:
            source_url = f"https://arxiv.org/abs/{arxiv_id}"
        else:
            # Fall back to DOI — PaperService will use abstract as full text.
            doi = (item.get("doi") or ids.get("doi", "")).lstrip("https://doi.org/")
            if not doi:
                continue
            arxiv_id = doi   # DOI used as the unique paper identifier
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
