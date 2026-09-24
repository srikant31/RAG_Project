"""
QueryDesk - LlamaIndex-backed hybrid retrieval orchestration.

Dense Pinecone retrieval and sparse BM25 retrieval remain backed by QueryDesk's
existing stores, while LlamaIndex handles reciprocal-rank fusion.
"""
from __future__ import annotations

import time
from typing import Optional

from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.core.llms.mock import MockLLM
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from QueryDesk.config import settings
from QueryDesk.core.ingestion.gemini_embedder import GeminiEmbedder
from QueryDesk.core.ingestion.pinecone_embedder import PineconeEmbedder
from QueryDesk.core.retrieval.bm25_store import BM25Store
from QueryDesk.core.retrieval.pinecone_store import PineconeStore
from QueryDesk.models.schemas import RetrievedChunk, RetrievalResult
from QueryDesk.utils.logger import logger


class _DensePineconeRetriever(BaseRetriever):
    """LlamaIndex retriever adapter for QueryDesk's Pinecone store."""

    def __init__(
        self,
        pinecone_store: PineconeStore,
        embedder: GeminiEmbedder | PineconeEmbedder,
        top_k: int,
    ) -> None:
        super().__init__()
        self._pinecone = pinecone_store
        self._embedder = embedder
        self._top_k = top_k

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        query_embedding = self._embedder.embed_query(query_bundle.query_str)
        chunks = self._pinecone.query(query_embedding, top_k=self._top_k)
        return [_retrieved_chunk_to_node(chunk) for chunk in chunks]


class _SparseBM25Retriever(BaseRetriever):
    """LlamaIndex retriever adapter for QueryDesk's BM25 store."""

    def __init__(self, bm25_store: BM25Store, top_k: int) -> None:
        super().__init__()
        self._bm25 = bm25_store
        self._top_k = top_k

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        chunks = self._bm25.query(query_bundle.query_str, top_k=self._top_k)
        return [_retrieved_chunk_to_node(chunk) for chunk in chunks]


def _retrieved_chunk_to_node(chunk: RetrievedChunk) -> NodeWithScore:
    node = TextNode(
        id_=chunk.chunk_id,
        text=chunk.content,
        metadata={
            "chunk_id": chunk.chunk_id,
            "doc_id": chunk.doc_id,
            "doc_name": chunk.doc_name,
            "page_number": chunk.page_number or 0,
            "dense_score": chunk.dense_score,
            "sparse_score": chunk.sparse_score,
        },
    )
    return NodeWithScore(node=node, score=chunk.final_score)


def _node_to_retrieved_chunk(node_with_score: NodeWithScore) -> RetrievedChunk:
    metadata = node_with_score.metadata or {}
    page_number = metadata.get("page_number")

    return RetrievedChunk(
        chunk_id=metadata.get("chunk_id", node_with_score.node_id),
        doc_id=metadata.get("doc_id", ""),
        doc_name=metadata.get("doc_name", "Unknown"),
        content=node_with_score.get_content(),
        page_number=page_number if page_number not in (0, "0", None) else None,
        dense_score=float(metadata.get("dense_score", 0.0) or 0.0),
        sparse_score=float(metadata.get("sparse_score", 0.0) or 0.0),
        final_score=float(node_with_score.score or 0.0),
    )


class HybridRetriever:
    """
    LlamaIndex-powered hybrid retrieval.

    QueryDesk's storage/indexing stays the same, but retrieval orchestration is now
    delegated to LlamaIndex QueryFusionRetriever using reciprocal-rank fusion.
    """

    def __init__(
        self,
        pinecone_store: PineconeStore,
        bm25_store: BM25Store,
        embedder: GeminiEmbedder | PineconeEmbedder | None = None,
    ) -> None:
        # Use configured embedder if none provided
        if embedder is None:
            if settings.pinecone_embedding_enabled:
                embedder = PineconeEmbedder(
                    model=settings.pinecone_embedding_model,
                    dimension=settings.embedding_dim
                )
                logger.info("Using Pinecone embedder for retrieval")
            else:
                embedder = GeminiEmbedder(dimension=settings.embedding_dim)
                logger.info("Using Gemini embedder for retrieval")
        
        self._dense = _DensePineconeRetriever(
            pinecone_store=pinecone_store,
            embedder=embedder,
            top_k=settings.top_k_results * 2,
        )
        self._sparse = _SparseBM25Retriever(
            bm25_store=bm25_store,
            top_k=settings.bm25_top_k * 2,
        )
        self._fusion = QueryFusionRetriever(
            retrievers=[self._dense, self._sparse],
            llm=MockLLM(max_tokens=1),
            mode=FUSION_MODES.RECIPROCAL_RANK,
            similarity_top_k=settings.top_k_results,
            num_queries=1,
            use_async=False,
            verbose=False,
        )
        logger.info("HybridRetriever initialized with LlamaIndex QueryFusionRetriever")

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
    ) -> RetrievalResult:
        """Execute hybrid retrieval and return QueryDesk's existing result schema."""
        k = top_k or settings.top_k_results
        start_time = time.time()

        logger.info(f"LlamaIndex hybrid retrieval for query: '{query[:80]}...'")

        nodes = self._fusion.retrieve(query)
        top_results = [_node_to_retrieved_chunk(node) for node in nodes[:k]]

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"LlamaIndex fusion complete: {len(top_results)} results "
            f"in {elapsed_ms:.1f}ms"
        )

        return RetrievalResult(
            query=query,
            chunks=top_results,
            retrieval_time_ms=elapsed_ms,
        )

    def as_llama_retriever(self):
        """Expose the underlying LlamaIndex retriever for query-engine synthesis."""
        return self._fusion
