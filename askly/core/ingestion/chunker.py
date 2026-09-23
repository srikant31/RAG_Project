"""
Askly — Semantic Chunker
Splits parsed document pages/sections into overlapping chunks
suitable for embedding and retrieval.
"""
from __future__ import annotations

import uuid
from typing import Optional

from askly.config import settings
from askly.models.schemas import DocumentChunk
from askly.utils.logger import logger


class DocumentChunker:
    """
    Splits document text into fixed-size overlapping chunks.
    Uses word-level splitting to preserve semantic boundaries.
    """

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ):
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap

    def chunk_document(
        self,
        pages: list[dict],
        doc_id: str,
        doc_name: str,
    ) -> list[DocumentChunk]:
        """
        Chunk all pages/sections of a document.

        Args:
            pages: List of {"text": str, "page": int | None, "metadata": dict}
            doc_id: Unique document ID
            doc_name: Human-readable document name

        Returns:
            List of DocumentChunk objects ready for embedding
        """
        all_chunks: list[DocumentChunk] = []
        chunk_index = 0

        for page_data in pages:
            text = page_data["text"]
            page_number = page_data.get("page")
            metadata = page_data.get("metadata", {})

            page_chunks = self._split_text(text)
            for chunk_text in page_chunks:
                if not chunk_text.strip():
                    continue

                chunk = DocumentChunk(
                    chunk_id=str(uuid.uuid4()),
                    doc_id=doc_id,
                    doc_name=doc_name,
                    content=chunk_text,
                    chunk_index=chunk_index,
                    page_number=page_number,
                    metadata={**metadata, "chunk_index": chunk_index},
                )
                all_chunks.append(chunk)
                chunk_index += 1

        logger.info(
            f"Chunked '{doc_name}': {len(pages)} pages → {len(all_chunks)} chunks "
            f"(size={self.chunk_size}, overlap={self.chunk_overlap})"
        )
        return all_chunks

    def _split_text(self, text: str) -> list[str]:
        """
        Split text into overlapping word-level chunks.
        Word-level splitting preserves token semantics better than char-level.
        """
        words = text.split()
        if not words:
            return []

        chunks = []
        start = 0

        while start < len(words):
            end = min(start + self.chunk_size, len(words))
            chunk = " ".join(words[start:end])
            chunks.append(chunk)

            if end >= len(words):
                break

            start += self.chunk_size - self.chunk_overlap

        return chunks
