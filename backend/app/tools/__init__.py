from .arxiv_tools import ARXIV_TOOL_MAP, search_arxiv_tool, fetch_paper_tool
from .vector_tools import VECTOR_TOOL_MAP, store_chunks_tool, semantic_search_tool
from .synthesis_tools import SYNTHESIS_TOOL_MAP, extract_claims_tool, verify_citation_tool

ALL_TOOL_MAP = {**ARXIV_TOOL_MAP, **VECTOR_TOOL_MAP, **SYNTHESIS_TOOL_MAP}
