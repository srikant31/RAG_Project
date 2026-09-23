"""
Askly — Pinecone Vector Store
Handles upsert and dense retrieval via Pinecone free-tier serverless.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pinecone import Pinecone, ServerlessSpec
from tenacity import retry, stop_after_attempt, wait_exponential

from askly.config import settings
from askly.models.schemas import DocumentChunk, RetrievedChunk
from askly.utils.logger import logger

REGISTRY_PATH = Path(".data/document_registry.json")
BM25_STORE_PATH = Path(".data/bm25_store.pkl")
BM25_META_PATH = Path(".data/bm25_corpus_meta.json")


class PineconeStore:
    """
    Manages all Pinecone operations: index creation, upsert, query, delete.
    Designed for Pinecone free tier (serverless, single index).
    """

    def __init__(self):
        self._pc = Pinecone(api_key=settings.pinecone_api_key)
        self._index_name = settings.pinecone_index_name
        self._index = self._get_or_create_index()
        logger.info(f"PineconeStore ready — index: '{self._index_name}'")

    def _cleanup_local_data(self):
        """Clean up local data files when index is recreated."""
        files_to_delete = [REGISTRY_PATH, BM25_STORE_PATH, BM25_META_PATH]
        deleted = []
        
        for file_path in files_to_delete:
            if file_path.exists():
                try:
                    file_path.unlink()
                    deleted.append(file_path.name)
                    logger.info(f"Deleted local data file: {file_path.name}")
                except Exception as e:
                    logger.warning(f"Failed to delete {file_path.name}: {e}")
        
        if deleted:
            logger.info(f"Auto-cleanup completed: deleted {len(deleted)} local data files")

    def _get_or_create_index(self):
        """Create index if it doesn't exist, else connect to existing."""
        existing = [idx.name for idx in self._pc.list_indexes()]
        if self._index_name not in existing:
            logger.info(f"Creating Pinecone index '{self._index_name}' with dimension {settings.embedding_dim}...")
            self._pc.create_index(
                name=self._index_name,
                dimension=settings.embedding_dim,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud="aws",
                    region=settings.pinecone_environment,
                ),
            )
            logger.info(f"Index '{self._index_name}' created successfully")
            
            # Auto-cleanup local data on index recreation
            self._cleanup_local_data()
        return self._pc.Index(self._index_name)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=5))
    def upsert_chunks(
        self,
        chunk_embeddings: list[tuple[DocumentChunk, list[float]]],
    ) -> int:
        """
        Upsert chunk embeddings into Pinecone.

        Args:
            chunk_embeddings: List of (chunk, embedding) tuples

        Returns:
            Number of vectors upserted
        """
        vectors = []
        for chunk, embedding in chunk_embeddings:
            vectors.append({
                "id": chunk.chunk_id,
                "values": embedding,
                "metadata": {
                    "doc_id": chunk.doc_id,
                    "doc_name": chunk.doc_name,
                    "content": chunk.content[:1000],  # Pinecone metadata limit
                    "chunk_index": chunk.chunk_index,
                    "page_number": chunk.page_number or 0,
                },
            })

        # Upsert in batches of 100 (Pinecone limit)
        batch_size = 100
        upserted = 0
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i : i + batch_size]
            self._index.upsert(vectors=batch)
            upserted += len(batch)
            logger.debug(f"Upserted batch {i // batch_size + 1}: {len(batch)} vectors")

        logger.info(f"Upserted {upserted} vectors into Pinecone")
        return upserted

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=5))
    def query(
        self,
        query_embedding: list[float],
        top_k: Optional[int] = None,
        filter_doc_id: Optional[str] = None,
    ) -> list[RetrievedChunk]:
        """
        Query Pinecone for nearest neighbours.

        Args:
            query_embedding: Query vector
            top_k: Number of results to return
            filter_doc_id: Optional filter to specific document

        Returns:
            List of RetrievedChunk sorted by relevance
        """
        k = top_k or settings.top_k_results
        query_filter = {"doc_id": {"$eq": filter_doc_id}} if filter_doc_id else None

        response = self._index.query(
            vector=query_embedding,
            top_k=k,
            include_metadata=True,
            filter=query_filter,
        )

        chunks = []
        for match in response.matches:
            meta = match.metadata or {}
            chunks.append(
                RetrievedChunk(
                    chunk_id=match.id,
                    doc_id=meta.get("doc_id", ""),
                    doc_name=meta.get("doc_name", "Unknown"),
                    content=meta.get("content", ""),
                    page_number=meta.get("page_number") or None,
                    dense_score=float(match.score),
                    final_score=float(match.score),
                )
            )

        logger.debug(f"Pinecone query returned {len(chunks)} results")
        return chunks

    def fetch_all_metadata(self) -> list[dict]:
        """
        Fetch all document metadata from Pinecone to rebuild local state.

        Returns:
            List of metadata dictionaries for all vectors in Pinecone
        """
        try:
            # Query with dummy vector to fetch all vectors
            response = self._index.query(
                vector=[0] * settings.embedding_dim,
                top_k=10000,
                include_metadata=True,
                filter={}
            )
            metadata_list = []
            for match in response.get("matches", []):
                metadata_list.append(match.metadata or {})
            logger.info(f"Fetched {len(metadata_list)} metadata entries from Pinecone")
            return metadata_list
        except Exception as e:
            logger.error(f"Failed to fetch metadata from Pinecone: {e}")
            return []

    def delete_document(self, doc_id: str) -> None:
        """Delete all vectors belonging to a document."""
        try:
            self._index.delete(filter={"doc_id": {"$eq": doc_id}})
            logger.info(f"Deleted all vectors for doc_id: {doc_id}")
        except Exception as e:
            logger.warning(f"Failed to delete vectors for doc_id {doc_id} (may not exist): {e}")

    def get_index_stats(self) -> dict:
        """Return index statistics."""
        try:
            stats = self._index.describe_index_stats()
            return {
                "total_vectors": stats.total_vector_count,
                "dimension": stats.dimension,
            }
        except Exception as e:
            logger.warning(f"Could not fetch index stats: {e}")
            return {"total_vectors": 0, "dimension": settings.embedding_dim}
