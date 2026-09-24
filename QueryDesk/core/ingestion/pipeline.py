"""
QueryDesk — Document Ingestion Pipeline
Orchestrates: Parse → Chunk → Embed → Store (Pinecone + BM25)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from QueryDesk.config import settings
from QueryDesk.core.ingestion.chunker import DocumentChunker
from QueryDesk.core.ingestion.gemini_embedder import GeminiEmbedder
from QueryDesk.core.ingestion.pinecone_embedder import PineconeEmbedder
from QueryDesk.core.ingestion.parser import DocumentParser
from QueryDesk.core.retrieval.bm25_store import BM25Store
from QueryDesk.core.retrieval.pinecone_store import PineconeStore
from QueryDesk.models.schemas import (
    DocumentRecord,
    DocumentStatus,
    DocumentUploadResult,
)
from QueryDesk.utils.logger import logger

REGISTRY_PATH = Path(".data/document_registry.json")


class IngestionPipeline:
    """
    Full document ingestion pipeline.
    Tracks all uploaded documents in a JSON registry.
    """

    def __init__(
        self,
        pinecone_store: PineconeStore,
        bm25_store: BM25Store,
    ):
        self._parser = DocumentParser()
        self._chunker = DocumentChunker()
        
        # Choose embedder based on config
        if settings.pinecone_embedding_enabled:
            self._embedder = PineconeEmbedder(
                model=settings.pinecone_embedding_model,
                dimension=settings.embedding_dim
            )
            logger.info("Using Pinecone embedder for embeddings")
        else:
            self._embedder = GeminiEmbedder(dimension=settings.embedding_dim)
            logger.info("Using Gemini embedder for embeddings")
        
        self._pinecone = pinecone_store
        self._bm25 = bm25_store
        self._registry: dict[str, dict] = self._load_registry()
        logger.info(
            f"IngestionPipeline ready — {len(self._registry)} documents in registry"
        )

    def ingest(self, file_path: str, doc_name: str) -> DocumentUploadResult:
        """
        Ingest a document through the full pipeline.

        Args:
            file_path: Path to the uploaded file
            doc_name: Human-readable document name

        Returns:
            DocumentUploadResult with status and details
        """
        doc_id = str(uuid.uuid4())
        path = Path(file_path)
        file_type = path.suffix.lstrip(".").lower()

        record = DocumentRecord(
            doc_id=doc_id,
            name=doc_name,
            file_type=file_type,
            size_bytes=path.stat().st_size if path.exists() else 0,
            status=DocumentStatus.PROCESSING,
        )
        self._update_registry(record)

        try:
            logger.info(f"Starting ingestion: '{doc_name}' ({file_type})")

            # ── Step 1: Parse ──────────────────────────────────────────────
            pages = self._parser.parse(file_path)
            if not pages:
                raise ValueError("Document parsed but no text content found")

            # ── Step 2: Chunk ──────────────────────────────────────────────
            chunks = self._chunker.chunk_document(pages, doc_id, doc_name)
            if not chunks:
                raise ValueError("Chunking produced no chunks")

            # ── Step 3: Embed ──────────────────────────────────────────────
            chunk_embeddings = self._embedder.embed_chunks(chunks)

            # ── Step 4: Store in Pinecone ──────────────────────────────────
            self._pinecone.upsert_chunks(chunk_embeddings)

            # ── Step 5: Store in BM25 ──────────────────────────────────────
            self._bm25.add_chunks(chunks)

            # ── Update registry ────────────────────────────────────────────
            record.chunk_count = len(chunks)
            record.status = DocumentStatus.INDEXED
            self._update_registry(record)

            logger.info(
                f"Ingestion complete: '{doc_name}' — "
                f"{len(chunks)} chunks indexed"
            )

            return DocumentUploadResult(
                success=True,
                doc_id=doc_id,
                doc_name=doc_name,
                chunks_indexed=len(chunks),
                message=f"Successfully indexed {len(chunks)} chunks from '{doc_name}'",
            )

        except Exception as e:
            logger.error(f"Ingestion failed for '{doc_name}': {e}")
            record.status = DocumentStatus.FAILED
            record.error_message = str(e)
            self._update_registry(record)
            return DocumentUploadResult(
                success=False,
                doc_id=doc_id,
                doc_name=doc_name,
                chunks_indexed=0,
                message=f"Ingestion failed for '{doc_name}'",
                error=str(e),
            )

    def delete_document(self, doc_id: str) -> bool:
        """Remove a document from all stores and registry."""
        try:
            self._pinecone.delete_document(doc_id)
            self._bm25.remove_document(doc_id)
            if doc_id in self._registry:
                del self._registry[doc_id]
                self._save_registry()
            logger.info(f"Document {doc_id} deleted from all stores")
            return True
        except Exception as e:
            logger.error(f"Failed to delete document {doc_id}: {e}")
            return False

    def get_all_documents(self) -> list[DocumentRecord]:
        """Return all documents in the registry."""
        records = []
        for data in self._registry.values():
            try:
                records.append(DocumentRecord(**data))
            except Exception as e:
                logger.warning(f"Skipping malformed registry entry: {e}")
        return sorted(records, key=lambda r: r.uploaded_at, reverse=True)

    def rebuild_registry_from_pinecone(self) -> None:
        """
        Rebuild the local registry from Pinecone metadata.
        Used on Streamlit Cloud restart to restore local state.
        """
        try:
            metadata_list = self._pinecone.fetch_all_metadata()
            if not metadata_list:
                logger.info("No metadata found in Pinecone, registry rebuild skipped")
                return

            # Build unique document records from metadata
            doc_records = {}
            for meta in metadata_list:
                doc_id = meta.get("doc_id")
                doc_name = meta.get("doc_name")
                if doc_id and doc_name:
                    if doc_id not in doc_records:
                        doc_records[doc_id] = {
                            "doc_id": doc_id,
                            "name": doc_name,
                            "file_type": "unknown",
                            "size_bytes": 0,
                            "status": "completed",
                            "uploaded_at": "1970-01-01T00:00:00",
                            "chunk_count": 0,
                        }
                    doc_records[doc_id]["chunk_count"] += 1

            # Update registry
            self._registry = doc_records
            self._save_registry()
            logger.info(f"Rebuilt registry with {len(doc_records)} documents from Pinecone")
        except Exception as e:
            logger.error(f"Failed to rebuild registry from Pinecone: {e}")

    def _update_registry(self, record: DocumentRecord) -> None:
        """Save/update a document record in the registry."""
        self._registry[record.doc_id] = json.loads(record.model_dump_json())
        self._save_registry()

    def _save_registry(self) -> None:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(self._registry, f, indent=2, default=str)

    def _load_registry(self) -> dict:
        if REGISTRY_PATH.exists():
            try:
                with open(REGISTRY_PATH, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load document registry: {e}")
        return {}
