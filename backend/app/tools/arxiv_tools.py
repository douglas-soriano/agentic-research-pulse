"""
arXiv tool definitions for agents.
All external HTTP calls use tenacity retry (1s→2s→4s, up to 3 retries).
"""
import time
import urllib.parse
from datetime import datetime

import feedparser
import httpx
import structlog

from app.resilience.retry import http_retry

logger = structlog.get_logger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_HTML_URL = "https://ar5iv.labs.arxiv.org/html/{arxiv_id}"


def search_arxiv(query: str, max_results: int = 5) -> dict:
    """Search arXiv and return structured paper metadata."""
    # arXiv asks automated clients to wait at least 3 s between requests.
    time.sleep(3)
    max_results = min(max_results, 5)
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    response = _fetch_with_arxiv_rate_limit(url)
    response.raise_for_status()

    feed = feedparser.parse(response.text)
    papers = []
    for entry in feed.entries:
        arxiv_id = entry.id.split("/abs/")[-1]
        published_str = entry.get("published", "")
        try:
            published_at = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
        except Exception:
            published_at = datetime.utcnow()

        abstract = entry.summary.replace("\n", " ").strip()
        papers.append({
            "arxiv_id": arxiv_id,
            "title": entry.title.replace("\n", " ").strip(),
            "authors": [a.name for a in entry.get("authors", [])][:3],
            "abstract": abstract[:400] + ("…" if len(abstract) > 400 else ""),
            "published_at": published_at.isoformat(),
            "url": f"https://arxiv.org/abs/{arxiv_id}",
        })

    return {"papers": papers, "total_found": len(papers)}


@http_retry
def _fetch_with_arxiv_rate_limit(url: str) -> httpx.Response:
    """Fetch arXiv URL with tenacity retry. arXiv 429 gets a 65s sleep before re-raising."""
    response = httpx.get(url, timeout=30)
    if response.status_code == 429:
        logger.warning("arxiv_rate_limited", url=url)
        time.sleep(65)
        response.raise_for_status()
    return response


def fetch_paper(arxiv_id: str) -> dict:
    """
    Fetch the readable text of an arXiv paper.
    Tries ar5iv HTML first (clean text), falls back to abstract.
    """
    time.sleep(3)
    html_url = ARXIV_HTML_URL.format(arxiv_id=arxiv_id)
    try:
        resp = _fetch_html_with_retry(html_url)
        final_url = str(resp.url)
        stayed_on_ar5iv = "ar5iv" in final_url
        if resp.status_code == 200 and stayed_on_ar5iv and len(resp.text) > 5000:
            text = _extract_text_from_html(resp.text)
            if len(text) > 2000:
                return {"arxiv_id": arxiv_id, "text": text, "source": "ar5iv"}
    except Exception as exc:
        logger.warning("ar5iv_fetch_failed", arxiv_id=arxiv_id, error=str(exc))

    # Fallback: fetch abstract via arXiv API
    params = {"id_list": arxiv_id, "max_results": 1}
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    try:
        resp = _fetch_with_arxiv_rate_limit(url)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        if feed.entries:
            entry = feed.entries[0]
            text = f"Title: {entry.title}\n\nAbstract: {entry.summary}"
            return {"arxiv_id": arxiv_id, "text": text, "source": "abstract"}
    except Exception as exc:
        logger.warning("arxiv_abstract_fetch_failed", arxiv_id=arxiv_id, error=str(exc))

    return {"arxiv_id": arxiv_id, "text": "", "source": "none", "error": "Could not fetch paper"}


@http_retry
def _fetch_html_with_retry(url: str) -> httpx.Response:
    return httpx.get(url, timeout=30, follow_redirects=True)


def _extract_text_from_html(html: str) -> str:
    import re
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<(p|div|h[1-6]|li|br)[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", "", html)
    lines = [line.strip() for line in html.splitlines() if line.strip()]
    return "\n".join(lines)[:50_000]


# ---------------------------------------------------------------------------
# Tool declarations (OpenAI function-calling format)
# ---------------------------------------------------------------------------

search_arxiv_tool = {
    "type": "function",
    "function": {
        "name": "search_arxiv",
        "description": (
            "Search arXiv for recent academic papers matching a query. "
            "Returns paper metadata: title, authors, abstract, arxiv_id, published_at."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, e.g. 'retrieval augmented generation'",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of papers to return (default 8, max 20)",
                },
            },
            "required": ["query"],
        },
    },
}

fetch_paper_tool = {
    "type": "function",
    "function": {
        "name": "fetch_paper",
        "description": (
            "Fetch the full readable text of an arXiv paper by its arxiv_id. "
            "Returns paper text for further processing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "arxiv_id": {
                    "type": "string",
                    "description": "The arXiv paper ID, e.g. '2305.14314'",
                },
            },
            "required": ["arxiv_id"],
        },
    },
}

ARXIV_TOOL_MAP = {
    "search_arxiv": search_arxiv,
    "fetch_paper": fetch_paper,
}
