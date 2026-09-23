"""
Askly — Pinecone Embedder
Generates embeddings using Pinecone's hosted inference API.
Includes retry logic and batch processing for reliability.
"""
from __future__ import annotations

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from askly.config import settings
from askly.models.schemas import DocumentChunk
from askly.utils.logger import logger


class PineconeEmbedder:
    """
    Wraps Pinecone's Inference API for embedding generation.
    Uses llama-text-embed-v2 (1024-dim default, supports 384/512/768/1024/2048).
    Free tier: 5M tokens/month on Starter plan.
    """

    BATCH_SIZE = 96  # Pinecone's max batch size for llama-text-embed-v2
    API_URL = "https://api.pinecone.io/embed"
    API_VERSION = "2026-04"
    
    # Available Pinecone embedding models
    MODELS = {
        "llama-text-embed-v2": {
            "default_dim": 1024,
            "supported_dims": [384, 512, 768, 1024, 2048],
            "max_sequence": 2048,
        },
        "multilingual-e5-large": {
            "default_dim": 1024,
            "supported_dims": [1024],
            "max_sequence": 512,
        },
    }

    def __init__(self, model: str = "llama-text-embed-v2", dimension: int | None = None):
        """
        Initialize Pinecone Embedder.
        
        Args:
            model: Pinecone model name (default: llama-text-embed-v2)
            dimension: Embedding dimension (default: from settings.embedding_dim)
        """
        self._api_key = settings.pinecone_api_key
        self._model = model
        self._dimension = dimension or settings.embedding_dim
        
        # Validate dimension for the model
        if model in self.MODELS:
            if self._dimension not in self.MODELS[model]["supported_dims"]:
                raise ValueError(
                    f"Dimension {self._dimension} not supported for {model}. "
                    f"Supported: {self.MODELS[model]['supported_dims']}"
                )
        
        logger.info(f"PineconeEmbedder initialized with model: {model}, dimension: {self._dimension}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException, Exception)),
        reraise=True,
    )
    def embed_text(self, text: str, task_type: str = "passage") -> list[float]:
        """
        Embed a single text string.

        Args:
            text: Text to embed
            task_type: "passage" for indexing documents, "query" for search queries

        Returns:
            Embedding vector as list of floats
        """
        try:
            headers = {
                "Api-Key": self._api_key,
                "Content-Type": "application/json",
                "X-Pinecone-Api-Version": self.API_VERSION,
            }
            
            payload = {
                "model": self._model,
                "parameters": {
                    "input_type": task_type,
                    "truncate": "END",
                },
                "inputs": [{"text": text}],
            }
            
            # Add dimension parameter if not using default
            if self._dimension != self.MODELS.get(self._model, {}).get("default_dim", 1024):
                payload["parameters"]["dimension"] = self._dimension
            
            response = requests.post(self.API_URL, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            embedding = data["data"][0]["values"]
            
            logger.debug(f"Embedded text (tokens: {data.get('usage', {}).get('total_tokens', 'N/A')})")
            return embedding
            
        except requests.RequestException as e:
            logger.error(f"Pinecone API request failed: {e}")
            raise
        except (KeyError, IndexError) as e:
            logger.error(f"Failed to parse Pinecone response: {e}")
            raise RuntimeError(f"Invalid response from Pinecone: {e}") from e
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            raise

    def embed_query(self, query: str) -> list[float]:
        """Embed a user query (asymmetric retrieval)."""
        return self.embed_text(query, task_type="query")

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
            
            # Process batch
            for chunk in batch:
                try:
                    embedding = self.embed_text(chunk.content, task_type="passage")
                    results.append((chunk, embedding))
                except Exception as e:
                    logger.error(f"Failed to embed chunk {chunk.chunk_id}: {e}")
                    raise RuntimeError(f"Embedding failed for chunk {chunk.chunk_id}: {e}") from e

        logger.info(f"Embedded {len(results)}/{total} chunks successfully")
        return results
