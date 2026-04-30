import time
import urllib.parse
from datetime import datetime

import feedparser
import httpx
import structlog

from app.constants import (
    ARXIV_ABSTRACT_MAX_CHARS,
    ARXIV_BACKOFF_SECONDS,
    ARXIV_DEFAULT_MAX_RESULTS,
    ARXIV_MAX_RESULTS,
    ARXIV_MIN_EXTRACTED_TEXT_CHARS,
    ARXIV_MIN_HTML_CHARS,
    ARXIV_RATE_LIMIT_SECONDS,
    EXTRACTED_TEXT_MAX_CHARS,
    HTTP_TIMEOUT_SECONDS,
)
from app.exceptions import ExternalServiceError
from app.resilience.retry import http_retry
from app.utils.time import utc_now

logger = structlog.get_logger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_HTML_URL = "https://ar5iv.labs.arxiv.org/html/{arxiv_id}"


def search_arxiv(query: str, max_results: int = ARXIV_DEFAULT_MAX_RESULTS) -> dict:
    time.sleep(ARXIV_RATE_LIMIT_SECONDS)
    capped_results = min(max_results, ARXIV_MAX_RESULTS)
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": capped_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    arxiv_response = _fetch_with_arxiv_rate_limit(url)
    arxiv_response.raise_for_status()

    feed = feedparser.parse(arxiv_response.text)
    papers = []
    for entry in feed.entries:
        arxiv_id = entry.id.split("/abs/")[-1]
        published_str = entry.get("published", "")
        try:
            published_at = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
        except ValueError as exc:
            logger.warning("arxiv_published_date_invalid", query=query, arxiv_id=arxiv_id, published=published_str, error=str(exc))
            published_at = utc_now()

        abstract = entry.summary.replace("\n", " ").strip()
        papers.append({
            "arxiv_id": arxiv_id,
            "title": entry.title.replace("\n", " ").strip(),
            "authors": [a.name for a in entry.get("authors", [])][:3],
            "abstract": abstract[:ARXIV_ABSTRACT_MAX_CHARS] + ("…" if len(abstract) > ARXIV_ABSTRACT_MAX_CHARS else ""),
            "published_at": published_at.isoformat(),
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            "source": "arxiv",
        })

    return {"papers": papers, "total_found": len(papers)}


@http_retry
def _fetch_with_arxiv_rate_limit(url: str) -> httpx.Response:
    arxiv_response = httpx.get(url, timeout=HTTP_TIMEOUT_SECONDS)
    if arxiv_response.status_code == 429:
        logger.warning("arxiv_rate_limited", url=url)
        time.sleep(ARXIV_BACKOFF_SECONDS)
        arxiv_response.raise_for_status()
    return arxiv_response


def fetch_paper(arxiv_id: str) -> dict:
    time.sleep(ARXIV_RATE_LIMIT_SECONDS)
    html_url = ARXIV_HTML_URL.format(arxiv_id=arxiv_id)
    try:
        html_response = _fetch_html_with_retry(html_url)
        final_url = str(html_response.url)
        stayed_on_ar5iv = "ar5iv" in final_url
        if html_response.status_code == 200 and stayed_on_ar5iv and len(html_response.text) > ARXIV_MIN_HTML_CHARS:
            text = _extract_text_from_html(html_response.text)
            if len(text) > ARXIV_MIN_EXTRACTED_TEXT_CHARS:
                return {"arxiv_id": arxiv_id, "text": text, "source": "ar5iv"}
    except httpx.HTTPError as exc:
        logger.warning("ar5iv_fetch_failed", arxiv_id=arxiv_id, error=str(exc))

    params = {"id_list": arxiv_id, "max_results": 1}
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    try:
        abstract_response = _fetch_with_arxiv_rate_limit(url)
        abstract_response.raise_for_status()
        feed = feedparser.parse(abstract_response.text)
        if feed.entries:
            entry = feed.entries[0]
            text = f"Title: {entry.title}\n\nAbstract: {entry.summary}"
            return {"arxiv_id": arxiv_id, "text": text, "source": "abstract"}
    except httpx.HTTPError as exc:
        logger.warning("arxiv_abstract_fetch_failed", arxiv_id=arxiv_id, error=str(exc))

    raise ExternalServiceError(f"Could not fetch arXiv paper {arxiv_id}")


@http_retry
def _fetch_html_with_retry(url: str) -> httpx.Response:
    return httpx.get(url, timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True)


def _extract_text_from_html(html: str) -> str:
    import re
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<(p|div|h[1-6]|li|br)[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", "", html)
    lines = [line.strip() for line in html.splitlines() if line.strip()]
    return "\n".join(lines)[:EXTRACTED_TEXT_MAX_CHARS]


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
