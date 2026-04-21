"""
Vector DB tool definitions — ChromaDB store/search.
"""
import chromadb
from chromadb.config import Settings as ChromaSettings
from google.genai import types

from app.config import settings as app_settings


def _get_client() -> chromadb.HttpClient:
    return chromadb.HttpClient(
        host=app_settings.chroma_host,
        port=app_settings.chroma_port,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _get_collection(client: chromadb.HttpClient) -> chromadb.Collection:
    return client.get_or_create_collection(
        name="paper_chunks",
        metadata={"hnsw:space": "cosine"},
    )


def store_chunks(chunks: list[dict]) -> dict:
    """
    Store text chunks with embeddings in ChromaDB.
    Each chunk must have: chunk_id, paper_id, text, metadata (dict).
    """
    if not chunks:
        return {"stored": 0}

    client = _get_client()
    collection = _get_collection(client)

    ids = [c["chunk_id"] for c in chunks]
    documents = [c["text"] for c in chunks]
    metadatas = [
        {**c.get("metadata", {}), "paper_id": c["paper_id"]}
        for c in chunks
    ]

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return {"stored": len(chunks)}


def semantic_search(query: str, paper_ids: list[str] | None = None, n_results: int = 10) -> dict:
    """
    Semantic search over stored chunks.
    Returns chunks with chunk_id, text, paper_id, and distance.
    """
    client = _get_client()
    collection = _get_collection(client)

    where = {"paper_id": {"$in": paper_ids}} if paper_ids else None

    results = collection.query(
        query_texts=[query],
        n_results=min(n_results, 20),
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    if results["ids"] and results["ids"][0]:
        for i, chunk_id in enumerate(results["ids"][0]):
            chunks.append({
                "chunk_id": chunk_id,
                "text": results["documents"][0][i],
                "paper_id": results["metadatas"][0][i].get("paper_id", ""),
                "title": results["metadatas"][0][i].get("title", ""),
                "arxiv_id": results["metadatas"][0][i].get("arxiv_id", ""),
                "distance": results["distances"][0][i],
            })

    return {"chunks": chunks, "total": len(chunks)}


def verify_chunk_exists(chunk_id: str) -> dict:
    """Check whether a chunk_id exists in the vector DB (for citation grounding)."""
    client = _get_client()
    collection = _get_collection(client)
    result = collection.get(ids=[chunk_id], include=["metadatas"])
    exists = bool(result["ids"])
    metadata = result["metadatas"][0] if exists else {}
    return {"exists": exists, "chunk_id": chunk_id, "metadata": metadata}


# ---------------------------------------------------------------------------
# Gemini tool declarations
# ---------------------------------------------------------------------------

store_chunks_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="store_chunks",
            description="Store text chunks from a paper into the vector database for semantic retrieval.",
            parameters={
                "type": "object",
                "properties": {
                    "chunks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "chunk_id": {"type": "string"},
                                "paper_id": {"type": "string"},
                                "text": {"type": "string"},
                                "metadata": {"type": "object"},
                            },
                            "required": ["chunk_id", "paper_id", "text"],
                        },
                    }
                },
                "required": ["chunks"],
            },
        )
    ]
)

semantic_search_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="semantic_search",
            description=(
                "Search the vector database for chunks semantically relevant to a query. "
                "Returns chunk_id, text, paper_id, and distance. "
                "Use chunk_id values as citation references."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Semantic search query"},
                    "paper_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of paper IDs to restrict search to",
                    },
                    "n_results": {
                        "type": "integer",
                        "description": "Number of results to return (default 10)",
                    },
                },
                "required": ["query"],
            },
        )
    ]
)

VECTOR_TOOL_MAP = {
    "store_chunks": store_chunks,
    "semantic_search": semantic_search,
    "verify_chunk_exists": verify_chunk_exists,
}
