"""
Askly — Pydantic Data Models
All domain schemas used across the application.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator
import uuid


# ── Enums ─────────────────────────────────────────────────────────────────────

class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class FeedbackType(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ── Document Models ───────────────────────────────────────────────────────────

class DocumentChunk(BaseModel):
    chunk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    doc_id: str
    doc_name: str
    content: str
    chunk_index: int
    page_number: Optional[int] = None
    metadata: dict = Field(default_factory=dict)


class DocumentRecord(BaseModel):
    doc_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    file_type: str  # "pdf" | "markdown"
    size_bytes: int
    chunk_count: int = 0
    status: DocumentStatus = DocumentStatus.PENDING
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    error_message: Optional[str] = None

    @field_validator("file_type")
    @classmethod
    def validate_file_type(cls, v: str) -> str:
        allowed = {"pdf", "markdown", "md"}
        if v.lower() not in allowed:
            raise ValueError(f"Unsupported file type: {v}. Must be one of {allowed}")
        return v.lower()


class DocumentUploadResult(BaseModel):
    success: bool
    doc_id: str
    doc_name: str
    chunks_indexed: int
    message: str
    error: Optional[str] = None


# ── Chat Models ───────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: MessageRole
    content: str
    sources: list[SourceReference] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    ragas_score: Optional[RAGASScore] = None


class SourceReference(BaseModel):
    doc_name: str
    chunk_content: str
    page_number: Optional[int] = None
    relevance_score: float = Field(ge=0.0, le=1.0)


class ChatSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    messages: list[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Retrieval Models ──────────────────────────────────────────────────────────

class RetrievedChunk(BaseModel):
    chunk_id: str
    doc_id: str
    doc_name: str
    content: str
    page_number: Optional[int] = None
    dense_score: float = 0.0
    sparse_score: float = 0.0
    final_score: float = 0.0


class RetrievalResult(BaseModel):
    query: str
    chunks: list[RetrievedChunk]
    retrieval_time_ms: float


# ── RAGAS Models ──────────────────────────────────────────────────────────────

class RAGASScore(BaseModel):
    faithfulness: Optional[float] = None
    answer_relevancy: Optional[float] = None
    context_precision: Optional[float] = None
    context_recall: Optional[float] = None
    answer_correctness: Optional[float] = None

    @property
    def overall(self) -> float:
        scores = [
            v for v in [
                self.faithfulness,
                self.answer_relevancy,
                self.context_precision,
            ]
            if v is not None
        ]
        return round(sum(scores) / len(scores), 3) if scores else 0.0


# ── Feedback Models ───────────────────────────────────────────────────────────

class FeedbackRecord(BaseModel):
    feedback_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message_id: str
    session_id: str
    feedback_type: FeedbackType
    comment: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Analytics Models ──────────────────────────────────────────────────────────

class AnalyticsSummary(BaseModel):
    total_queries: int = 0
    total_evaluations: int = 0
    positive_feedback: int = 0
    negative_feedback: int = 0
    avg_faithfulness: float = 0.0
    avg_relevancy: float = 0.0
    avg_precision: float = 0.0
    avg_overall: float = 0.0
    total_documents: int = 0
    total_chunks: int = 0
    knowledge_gaps: list[str] = Field(default_factory=list)
