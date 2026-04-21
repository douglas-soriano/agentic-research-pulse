"""
EmbeddingService — chunks paper text and stores chunks in ChromaDB.
ChromaDB handles embedding internally via its default sentence-transformers model.
"""
import re
import uuid

from app.config import settings
from app.tools.vector_tools import store_chunks


class EmbeddingService:
    def chunk_and_embed(self, paper_id: str, arxiv_id: str, title: str, text: str) -> int:
        """
        Splits text into overlapping chunks by approximate token count,
        stores them in ChromaDB. Returns the number of chunks stored.
        """
        chunks = self._chunk_text(text, paper_id, arxiv_id, title)
        if not chunks:
            return 0
        result = store_chunks(chunks)
        return result["stored"]

    def _chunk_text(self, text: str, paper_id: str, arxiv_id: str, title: str) -> list[dict]:
        # Split into sentences then group into chunks by word count
        # (rough proxy for tokens: 1 token ≈ 0.75 words)
        target_words = int(settings.chunk_size_tokens * 0.75)
        overlap_words = int(settings.chunk_overlap_tokens * 0.75)

        sentences = self._split_sentences(text)
        chunks = []
        current_words: list[str] = []
        chunk_sentences: list[str] = []

        for sentence in sentences:
            words = sentence.split()
            if len(current_words) + len(words) > target_words and current_words:
                chunk_text = " ".join(chunk_sentences)
                chunks.append(self._make_chunk(chunk_text, paper_id, arxiv_id, title, len(chunks)))
                # Slide window back by overlap
                words_to_keep = current_words[-overlap_words:] if overlap_words else []
                current_words = words_to_keep
                # Find matching sentences for the kept words
                kept_text = " ".join(words_to_keep)
                chunk_sentences = [kept_text] if kept_text else []
            current_words.extend(words)
            chunk_sentences.append(sentence)

        if current_words:
            chunk_text = " ".join(chunk_sentences)
            chunks.append(self._make_chunk(chunk_text, paper_id, arxiv_id, title, len(chunks)))

        return chunks

    def _split_sentences(self, text: str) -> list[str]:
        text = text.replace("\n\n", " <PARA> ").replace("\n", " ")
        # Simple sentence splitter
        parts = re.split(r"(?<=[.!?])\s+", text)
        sentences = []
        for p in parts:
            p = p.replace("<PARA>", "").strip()
            if p:
                sentences.append(p)
        return sentences

    def _make_chunk(self, text: str, paper_id: str, arxiv_id: str, title: str, idx: int) -> dict:
        return {
            "chunk_id": f"{paper_id}::chunk::{idx}",
            "paper_id": paper_id,
            "text": text[:4000],  # Safety cap
            "metadata": {
                "arxiv_id": arxiv_id,
                "title": title,
                "chunk_index": idx,
            },
        }
