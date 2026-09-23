"""
Askly — BM25 Sparse Retrieval Store
In-memory BM25 index for keyword-based sparse retrieval.
Persists corpus to disk for survival across restarts.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Optional

from rank_bm25 import BM25Okapi

from askly.config import settings
from askly.models.schemas import DocumentChunk, RetrievedChunk
from askly.utils.logger import logger

BM25_STORE_PATH = Path(".data/bm25_store.pkl")
CORPUS_META_PATH = Path(".data/bm25_corpus_meta.json")


class BM25Store:
    """
    Maintains an in-memory BM25 index over all document chunks.
    Persisted to disk as a pickle file for restart survival.
    """

    def __init__(self):
        self._corpus: list[list[str]] = []       # tokenized docs
        self._metadata: list[dict] = []          # chunk metadata
        self._bm25: Optional[BM25Okapi] = None
        self._load()
        logger.info(f"BM25Store ready — {len(self._corpus)} documents indexed")

    def add_chunks(self, chunks: list[DocumentChunk]) -> None:
        """Add chunks to the BM25 index."""
        for chunk in chunks:
            tokens = self._tokenize(chunk.content)
            self._corpus.append(tokens)
            self._metadata.append({
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "doc_name": chunk.doc_name,
                "content": chunk.content,
                "page_number": chunk.page_number,
            })

        self._rebuild_index()
        self._save()
        logger.info(f"BM25Store: added {len(chunks)} chunks, total={len(self._corpus)}")

    def query(self, query: str, top_k: Optional[int] = None) -> list[RetrievedChunk]:
        """
        Query BM25 index for keyword-relevant chunks.

        Returns:
            List of RetrievedChunk sorted by BM25 score descending
        """
        k = top_k or settings.bm25_top_k

        if not self._bm25 or not self._corpus:
            logger.warning("BM25Store is empty — no results returned")
            return []

        tokens = self._tokenize(query)
        scores = self._bm25.get_scores(tokens)

        # Get top-k indices by score
        top_indices = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True
        )[:k]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score <= 0:
                continue
            meta = self._metadata[idx]
            results.append(
                RetrievedChunk(
                    chunk_id=meta["chunk_id"],
                    doc_id=meta["doc_id"],
                    doc_name=meta["doc_name"],
                    content=meta["content"],
                    page_number=meta.get("page_number"),
                    sparse_score=score,
                    final_score=score,
                )
            )

        logger.debug(f"BM25 query returned {len(results)} results")
        return results

    def remove_document(self, doc_id: str) -> None:
        """Remove all chunks belonging to a document from the BM25 index."""
        original_count = len(self._corpus)
        filtered = [
            (tokens, meta)
            for tokens, meta in zip(self._corpus, self._metadata)
            if meta["doc_id"] != doc_id
        ]

        if filtered:
            self._corpus, self._metadata = zip(*filtered)
            self._corpus = list(self._corpus)
            self._metadata = list(self._metadata)
        else:
            self._corpus = []
            self._metadata = []

        self._rebuild_index()
        self._save()
        removed = original_count - len(self._corpus)
        logger.info(f"BM25Store: removed {removed} chunks for doc_id={doc_id}")

    def _rebuild_index(self) -> None:
        """Rebuild BM25 index from current corpus."""
        if self._corpus:
            self._bm25 = BM25Okapi(self._corpus)
        else:
            self._bm25 = None

    def _tokenize(self, text: str) -> list[str]:
        """Simple whitespace + lowercase tokenizer."""
        return text.lower().split()

    def get_all_chunks(self) -> list[dict]:
        """Return all chunk metadata for browsing the explorer."""
        return list(self._metadata)

    def search_chunks(self, keyword: str, limit: int = 20) -> list[dict]:
        """
        Search chunks by keyword substring match (case-insensitive).
        Used by the Document Explorer for quick filtering.
        """
        keyword_lower = keyword.lower()
        results = []
        for meta in self._metadata:
            if keyword_lower in meta.get("content", "").lower():
                results.append(meta)
                if len(results) >= limit:
                    break
        return results

    def get_chunks_for_document(self, doc_id: str) -> list[dict]:
        """Return all chunks belonging to a specific document."""
        return [m for m in self._metadata if m.get("doc_id") == doc_id]

    def rebuild_from_pinecone_metadata(self, metadata_list: list[dict]) -> None:
        """
        Rebuild BM25 index from Pinecone metadata.
        Used on Streamlit Cloud restart to restore local state.

        Args:
            metadata_list: List of metadata dictionaries from Pinecone
        """
        try:
            if not metadata_list:
                logger.info("No metadata provided, BM25 rebuild skipped")
                return

            self._corpus = []
            self._metadata = []

            for meta in metadata_list:
                content = meta.get("content", "")
                if content:
                    tokens = self._tokenize(content)
                    self._corpus.append(tokens)
                    self._metadata.append({
                        "chunk_id": meta.get("chunk_id", ""),
                        "doc_id": meta.get("doc_id", ""),
                        "doc_name": meta.get("doc_name", "Unknown"),
                        "content": content,
                        "page_number": meta.get("page_number"),
                    })

            self._rebuild_index()
            self._save()
            logger.info(f"Rebuilt BM25 index with {len(self._corpus)} chunks from Pinecone metadata")
        except Exception as e:
            logger.error(f"Failed to rebuild BM25 from Pinecone metadata: {e}")

    def _save(self) -> None:
        """Persist BM25 corpus and metadata to disk."""
        try:
            BM25_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(BM25_STORE_PATH, "wb") as f:
                pickle.dump({"corpus": self._corpus, "metadata": self._metadata}, f)
        except Exception as e:
            logger.warning(f"BM25 persistence failed: {e}")

    def _load(self) -> None:
        """Load persisted BM25 corpus from disk if available."""
        if BM25_STORE_PATH.exists():
            try:
                with open(BM25_STORE_PATH, "rb") as f:
                    data = pickle.load(f)
                self._corpus = data.get("corpus", [])
                self._metadata = data.get("metadata", [])
                self._rebuild_index()
                logger.info(f"BM25Store loaded {len(self._corpus)} docs from disk")
            except Exception as e:
                logger.warning(f"Failed to load BM25 store from disk: {e}")
                self._corpus = []
                self._metadata = []
