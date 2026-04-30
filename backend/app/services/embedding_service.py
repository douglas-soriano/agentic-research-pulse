import re

from app.constants import CHUNK_TEXT_MAX_CHARS, WORDS_PER_TOKEN_ESTIMATE
from app.config import settings
from app.tools.vector_tools import store_chunks


class EmbeddingService:
    def chunk_and_embed(self, paper_id: str, arxiv_id: str, title: str, text: str) -> int:
        chunks = self._chunk_text(text, paper_id, arxiv_id, title)
        if not chunks:
            return 0
        storage_result = store_chunks(chunks)
        return storage_result["stored"]

    def _chunk_text(self, text: str, paper_id: str, arxiv_id: str, title: str) -> list[dict]:
        target_words = int(settings.chunk_size_tokens * WORDS_PER_TOKEN_ESTIMATE)
        overlap_words = int(settings.chunk_overlap_tokens * WORDS_PER_TOKEN_ESTIMATE)

        sentences = self._split_sentences(text)
        chunks = []
        current_words: list[str] = []
        chunk_sentences: list[str] = []

        for sentence in sentences:
            words = sentence.split()
            if len(current_words) + len(words) > target_words and current_words:
                chunk_text = " ".join(chunk_sentences)
                chunks.append(self._make_chunk(chunk_text, paper_id, arxiv_id, title, len(chunks)))
                words_to_keep = current_words[-overlap_words:] if overlap_words else []
                current_words = words_to_keep
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
            "text": text[:CHUNK_TEXT_MAX_CHARS],
            "metadata": {
                "arxiv_id": arxiv_id,
                "title": title,
                "chunk_index": idx,
            },
        }
