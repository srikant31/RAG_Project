"""
Askly — Gemini Embedder
Generates embeddings using gemini-embedding-001 via google-genai SDK.
Includes retry logic and batch processing for reliability.
"""
from __future__ import annotations

from google import genai
from google.genai import types
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from askly.config import settings
from askly.models.schemas import DocumentChunk
from askly.utils.logger import logger


class GeminiEmbedder:
    """
    Wraps the Gemini Embedding API with batching and retry logic.
    Uses google-genai SDK (from google import genai).
    Model: gemini-embedding-001 (GA, 3072-dim, 100+ languages)
    Supports configurable output dimensionality via MRL.
    """

    BATCH_SIZE = 10

    def __init__(self, dimension: int | None = None):
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_embedding_model
        self._dimension = dimension or settings.embedding_dim
        logger.info(f"GeminiEmbedder initialized with model: {self._model}, dimension: {self._dimension}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def embed_text(self, text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
        """
        Embed a single text string.

        Args:
            text: Text to embed
            task_type: RETRIEVAL_DOCUMENT for indexing, RETRIEVAL_QUERY for queries

        Returns:
            Embedding vector as list of floats
        """
        try:
            result = self._client.models.embed_content(
                model=self._model,
                contents=text,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=self._dimension,
                ),
            )
            return result.embeddings[0].values
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            raise

    def embed_query(self, query: str) -> list[float]:
        """Embed a user query (asymmetric retrieval)."""
        return self.embed_text(query, task_type="RETRIEVAL_QUERY")

    def embed_chunks(self, chunks: list[DocumentChunk]) -> list[tuple[DocumentChunk, list[float]]]:
        """Embed a list of document chunks in batches."""
        results = []
        total = len(chunks)

        for i in range(0, total, self.BATCH_SIZE):
            batch = chunks[i : i + self.BATCH_SIZE]
            logger.info(
                f"Embedding batch {i // self.BATCH_SIZE + 1}/"
                f"{(total + self.BATCH_SIZE - 1) // self.BATCH_SIZE} "
                f"({len(batch)} chunks)"
            )
            for chunk in batch:
                try:
                    embedding = self.embed_text(chunk.content)
                    results.append((chunk, embedding))
                except Exception as e:
                    logger.error(f"Failed to embed chunk {chunk.chunk_id}: {e}")
                    raise RuntimeError(f"Embedding failed for chunk {chunk.chunk_id}: {e}") from e

        logger.info(f"Embedded {len(results)}/{total} chunks successfully")
        return results