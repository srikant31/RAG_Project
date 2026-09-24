"""
QueryDesk — Centralized Configuration
All settings loaded from environment variables via Pydantic Settings.
"""
from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Gemini ────────────────────────────────
    gemini_api_key: str = Field(..., description="Google Gemini API key")
    gemini_llm_model: str = Field(
        default="gemini-2.5-flash",
        description="Gemini LLM model identifier",
    )
    gemini_embedding_model: str = Field(
        default="gemini-embedding-2-preview",
        description="Gemini embedding model identifier",
    )

    # ── Pinecone ──────────────────────────────
    pinecone_api_key: str = Field(..., description="Pinecone API key")
    pinecone_index_name: str = Field(
        default="QueryDesk-index", description="Pinecone index name"
    )
    pinecone_environment: str = Field(
        default="us-east-1", description="Pinecone environment/region"
    )
    pinecone_embedding_model: str = Field(
        default="llama-text-embed-v2", description="Pinecone embedding model"
    )
    pinecone_embedding_enabled: bool = Field(
        default=True, description="Use Pinecone embedder instead of Gemini"
    )

    # ── Embedding ─────────────────────────────
    embedding_dim: int = Field(
        default=1024, description="Embedding dimension (common for both Gemini and Pinecone)"
    )

    # ── Chunking ──────────────────────────────
    chunk_size: int = Field(default=512, ge=128, le=2048)
    chunk_overlap: int = Field(default=50, ge=0, le=256)

    # ── Retrieval ─────────────────────────────
    top_k_results: int = Field(default=10, ge=1, le=50)
    bm25_top_k: int = Field(default=10, ge=1, le=50)

    # ── RAGAS ─────────────────────────────────
    ragas_enabled: bool = Field(default=True)
    ragas_gemini_enabled: bool = Field(default=False, description="Use Gemini for RAGAS evaluation (if false, uses heuristic only)")

    @field_validator("chunk_overlap")
    @classmethod
    def overlap_less_than_chunk(cls, v: int, info) -> int:
        chunk_size = info.data.get("chunk_size", 512)
        if v >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton — call this everywhere."""
    return Settings()


settings = get_settings()
