"""
arXiv tool definitions for agents.
Each entry is both the Python callable and the Gemini FunctionDeclaration.
"""
import time
import urllib.parse
from datetime import datetime

import feedparser
import httpx
from google.genai import types

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_HTML_URL = "https://ar5iv.labs.arxiv.org/html/{arxiv_id}"


def search_arxiv(query: str, max_results: int = 8) -> dict:
    """Search arXiv and return structured paper metadata."""
    params = {
        "search_query": f"all:{urllib.parse.quote(query)}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    response = httpx.get(url, timeout=30)
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

        papers.append({
            "arxiv_id": arxiv_id,
            "title": entry.title.replace("\n", " ").strip(),
            "authors": [a.name for a in entry.get("authors", [])],
            "abstract": entry.summary.replace("\n", " ").strip(),
            "published_at": published_at.isoformat(),
            "url": f"https://arxiv.org/abs/{arxiv_id}",
        })
        time.sleep(0.3)

    return {"papers": papers, "total_found": len(papers)}


def fetch_paper(arxiv_id: str) -> dict:
    """
    Fetch the readable text of an arXiv paper.
    Tries ar5iv HTML first (clean text), falls back to abstract.
    """
    html_url = ARXIV_HTML_URL.format(arxiv_id=arxiv_id)
    try:
        resp = httpx.get(html_url, timeout=30, follow_redirects=True)
        if resp.status_code == 200 and len(resp.text) > 5000:
            text = _extract_text_from_html(resp.text)
            if len(text) > 2000:
                return {"arxiv_id": arxiv_id, "text": text, "source": "ar5iv"}
    except Exception:
        pass

    params = {"id_list": arxiv_id, "max_results": 1}
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.text)
    if feed.entries:
        entry = feed.entries[0]
        text = f"Title: {entry.title}\n\nAbstract: {entry.summary}"
        return {"arxiv_id": arxiv_id, "text": text, "source": "abstract"}

    return {"arxiv_id": arxiv_id, "text": "", "source": "none", "error": "Could not fetch paper"}


def _extract_text_from_html(html: str) -> str:
    import re
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<(p|div|h[1-6]|li|br)[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", "", html)
    lines = [line.strip() for line in html.splitlines() if line.strip()]
    return "\n".join(lines)[:50_000]


# ---------------------------------------------------------------------------
# Gemini tool declarations
# ---------------------------------------------------------------------------

search_arxiv_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_arxiv",
            description=(
                "Search arXiv for recent academic papers matching a query. "
                "Returns paper metadata: title, authors, abstract, arxiv_id, published_at."
            ),
            parameters={
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
        )
    ]
)

fetch_paper_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="fetch_paper",
            description=(
                "Fetch the full readable text of an arXiv paper by its arxiv_id. "
                "Returns paper text for further processing."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "arxiv_id": {
                        "type": "string",
                        "description": "The arXiv paper ID, e.g. '2305.14314'",
                    },
                },
                "required": ["arxiv_id"],
            },
        )
    ]
)

ARXIV_TOOL_MAP = {
    "search_arxiv": search_arxiv,
    "fetch_paper": fetch_paper,
}
