import threading

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings as app_settings
from app.exceptions import DataStoreError


_lock = threading.Lock()
_collection: chromadb.Collection | None = None


def _get_collection() -> chromadb.Collection:
    global _collection
    if _collection is None:
        with _lock:
            if _collection is None:
                client = chromadb.HttpClient(
                    host=app_settings.chroma_host,
                    port=app_settings.chroma_port,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
                _collection = client.get_or_create_collection(
                    name="paper_chunks",
                    metadata={"hnsw:space": "cosine"},
                )
    return _collection


def store_chunks(chunks: list[dict]) -> dict:
    if not chunks:
        return {"stored": 0}

    collection = _get_collection()

    ids = [c["chunk_id"] for c in chunks]
    documents = [c["text"] for c in chunks]
    metadatas = [
        {**c.get("metadata", {}), "paper_id": c["paper_id"]}
        for c in chunks
    ]

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return {"stored": len(chunks)}


def semantic_search(query: str = "", paper_ids: list[str] | None = None, n_results: int = 10) -> dict:
    if not query:
        return {
            "chunks": [],
            "total": 0,
            "error": "Missing required argument: query. Call semantic_search(query='your search term', ...).",
        }

    collection = _get_collection()

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


def paper_has_chunks(arxiv_id: str) -> bool:
    try:
        collection = _get_collection()
        stored_chunks = collection.get(
            where={"arxiv_id": arxiv_id},
            limit=1,
            include=[],
        )
        return bool(stored_chunks["ids"])
    except Exception as exc:
        raise DataStoreError(f"Could not check stored chunks for {arxiv_id}") from exc


def verify_chunk_exists(chunk_id: str) -> dict:
    collection = _get_collection()
    stored_chunk = collection.get(ids=[chunk_id], include=["metadatas"])
    exists = bool(stored_chunk["ids"])
    metadata = stored_chunk["metadatas"][0] if exists else {}
    return {"exists": exists, "chunk_id": chunk_id, "metadata": metadata}


store_chunks_tool = {
    "type": "function",
    "function": {
        "name": "store_chunks",
        "description": "Store text chunks from a paper into the vector database for semantic retrieval.",
        "parameters": {
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
    },
}

semantic_search_tool = {
    "type": "function",
    "function": {
        "name": "semantic_search",
        "description": (
            "Search the vector database for chunks semantically relevant to a query. "
            "Returns chunk_id, text, paper_id, and distance. "
            "Use chunk_id values as citation references."
        ),
        "parameters": {
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
    },
}

VECTOR_TOOL_MAP = {
    "store_chunks": store_chunks,
    "semantic_search": semantic_search,
    "verify_chunk_exists": verify_chunk_exists,
}
