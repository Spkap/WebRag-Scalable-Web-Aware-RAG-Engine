from __future__ import annotations

from datetime import datetime
from typing import Any
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl

from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    DateTime,
    JSON,
    Float,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func, text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class URLIngestionJob(Base):
    """SQLAlchemy model mapping for url_ingestion_jobs table.

    Mirrors the schema created in scripts/init_db.sql.
    """

    __tablename__ = "url_ingestion_jobs"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    url = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, server_default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    chunk_count = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    processing_time_seconds = Column(Float, default=0.0)
    error_message = Column(Text, nullable=True)
    error_traceback = Column(Text, nullable=True)
    celery_task_id = Column(String(255), nullable=True)
    # 'metadata' is reserved on Declarative base; map the DB column 'metadata' to
    # an attribute named `metadata_json` on the model to avoid conflicts with
    # SQLAlchemy's class-level `metadata` attribute.
    metadata_json = Column('metadata', JSON, default={})

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed')", name="ck_status_values"),
    )

    def __repr__(self) -> str:  # pragma: no cover - simple repr
        return (
            f"<URLIngestionJob id={self.id!s} url={self.url!s} status={self.status!s} "
            f"created_at={self.created_at!r} completed_at={self.completed_at!r}>"
        )


# ----------------------
# Pydantic request/response models
# ----------------------


class IngestURLRequest(BaseModel):
    """Request payload for creating an ingestion job."""

    url: HttpUrl = Field(..., description="HTTP or HTTPS URL to ingest")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata attached to the URL")


class QueryRequest(BaseModel):
    """Request payload for running a query against the vector store."""

    question: str = Field(..., min_length=1, description="The natural language question to answer")
    top_k: int = Field(5, ge=1, le=50, description="Number of top results to return")
    filters: Optional[Dict[str, Any]] = Field(None, description="Optional filters to apply to retrieval")


class IngestURLResponse(BaseModel):
    job_id: UUID
    status: str
    message: str
    estimated_time_seconds: int = 30


class SourceChunk(BaseModel):
    text: str
    source_url: Optional[str]
    relevance_score: float


class QueryResponse(BaseModel):
    answer: str
    sources: List[SourceChunk]
    metadata: Dict[str, Any]


class JobStatusResponse(BaseModel):
    job_id: UUID
    status: str
    url: str
    created_at: datetime
    completed_at: Optional[datetime]
    processing_time_seconds: Optional[float]
    chunk_count: int
    error_message: Optional[str]


class HealthResponse(BaseModel):
    status: str
    services: Dict[str, Any]
    timestamp: datetime
    version: str
