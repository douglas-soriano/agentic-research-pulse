"""
Synthesis tool definitions — claim extraction and citation verification.
"""
from app.tools.vector_tools import verify_chunk_exists


def extract_claims(paper_id: str, chunks: list[dict]) -> dict:
    """
    Validate and normalise extracted claims.
    The LLM drives extraction; this validates the output format.
    """
    validated = []
    for chunk in chunks:
        if not chunk.get("chunk_id") or not chunk.get("text"):
            continue
        validated.append({
            "paper_id": paper_id,
            "chunk_id": chunk["chunk_id"],
            "text": chunk["text"],
            "category": chunk.get("category", "finding"),
            "confidence": float(chunk.get("confidence", 0.8)),
        })
    return {"claims": validated, "count": len(validated)}


def verify_citation(chunk_id: str, paper_id: str) -> dict:
    """
    Verify a citation is grounded — chunk must exist in vector DB
    AND belong to the claimed paper.
    """
    result = verify_chunk_exists(chunk_id)
    if not result["exists"]:
        return {"verified": False, "chunk_id": chunk_id, "reason": "chunk not found in vector DB"}

    stored_paper_id = result["metadata"].get("paper_id", "")
    if stored_paper_id != paper_id:
        return {
            "verified": False,
            "chunk_id": chunk_id,
            "reason": f"chunk belongs to paper {stored_paper_id}, not {paper_id}",
        }

    return {"verified": True, "chunk_id": chunk_id, "paper_id": paper_id}


# ---------------------------------------------------------------------------
# Tool declarations (OpenAI function-calling format)
# ---------------------------------------------------------------------------

extract_claims_tool = {
    "type": "function",
    "function": {
        "name": "extract_claims",
        "description": (
            "Extract and validate structured claims from paper chunks. "
            "Each claim must include a chunk_id that traces back to the source text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "paper_id": {"type": "string"},
                "chunks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "chunk_id": {"type": "string", "description": "ID of the source chunk"},
                            "text": {"type": "string", "description": "The claim text"},
                            "category": {
                                "type": "string",
                                "description": "One of: finding, method, limitation, contribution",
                            },
                            "confidence": {
                                "type": "number",
                                "description": "Confidence 0.0–1.0",
                            },
                        },
                        "required": ["chunk_id", "text"],
                    },
                },
            },
            "required": ["paper_id", "chunks"],
        },
    },
}

verify_citation_tool = {
    "type": "function",
    "function": {
        "name": "verify_citation",
        "description": (
            "Verify that a citation (chunk_id + paper_id pair) is grounded in the vector DB. "
            "MUST be called for every citation before including it in the synthesis. "
            "Unverified citations must be removed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chunk_id": {"type": "string"},
                "paper_id": {"type": "string"},
            },
            "required": ["chunk_id", "paper_id"],
        },
    },
}

SYNTHESIS_TOOL_MAP = {
    "extract_claims": extract_claims,
    "verify_citation": verify_citation,
}
