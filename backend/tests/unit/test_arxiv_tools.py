from unittest.mock import MagicMock, patch

import pytest

from app.tools.arxiv_tools import search_arxiv

ATOM_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2005.11401v1</id>
    <title>Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks</title>
    <summary>We explore a general-purpose fine-tuning recipe for RAG.</summary>
    <published>2020-05-22T00:00:00Z</published>
    <author><name>Patrick Lewis</name></author>
    <author><name>Ethan Perez</name></author>
    <author><name>Aleksandara Piktus</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2110.01168v1</id>
    <title>Improving language models by retrieving from trillions of tokens</title>
    <summary>We enhance autoregressive language models by conditioning on document chunks.</summary>
    <published>2021-10-04T00:00:00Z</published>
    <author><name>Sebastian Borgeaud</name></author>
  </entry>
</feed>
"""


def _make_mock_response(text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


@patch("time.sleep")
@patch("app.tools.arxiv_tools._fetch_with_arxiv_rate_limit")
def test_search_arxiv_returns_expected_fields(mock_fetch, mock_sleep):
    mock_fetch.return_value = _make_mock_response(ATOM_FEED)

    result = search_arxiv("retrieval augmented generation", max_results=2)

    papers = result["papers"]
    assert len(papers) == 2
    for paper in papers:
        assert "arxiv_id" in paper
        assert "title" in paper
        assert "authors" in paper
        assert "abstract" in paper
        assert isinstance(paper["authors"], list)
        assert paper["arxiv_id"]
        assert paper["title"]


@patch("time.sleep")
@patch("app.tools.arxiv_tools._fetch_with_arxiv_rate_limit")
def test_search_arxiv_arxiv_id_is_parsed_correctly(mock_fetch, mock_sleep):
    mock_fetch.return_value = _make_mock_response(ATOM_FEED)

    result = search_arxiv("rag")

    assert result["papers"][0]["arxiv_id"] == "2005.11401v1"


@patch("time.sleep")
@patch("app.tools.arxiv_tools._fetch_with_arxiv_rate_limit")
def test_search_arxiv_truncates_long_abstract(mock_fetch, mock_sleep):
    long_abstract = "word " * 200
    feed = ATOM_FEED.replace(
        "We explore a general-purpose fine-tuning recipe for RAG.",
        long_abstract,
    )
    mock_fetch.return_value = _make_mock_response(feed)

    result = search_arxiv("rag")

    assert len(result["papers"][0]["abstract"]) <= 401


@patch("time.sleep")
@patch("app.tools.arxiv_tools._fetch_with_arxiv_rate_limit")
def test_search_arxiv_caps_max_results_at_5(mock_fetch, mock_sleep):
    mock_fetch.return_value = _make_mock_response(ATOM_FEED)

    search_arxiv("rag", max_results=100)

    call_url = mock_fetch.call_args[0][0]
    assert "max_results=5" in call_url


@patch("time.sleep")
@patch("app.tools.arxiv_tools._fetch_with_arxiv_rate_limit")
def test_search_arxiv_sleeps_between_requests(mock_fetch, mock_sleep):
    mock_fetch.return_value = _make_mock_response(ATOM_FEED)

    search_arxiv("rag")

    mock_sleep.assert_called_once_with(3)
