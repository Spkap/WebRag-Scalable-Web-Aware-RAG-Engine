from __future__ import annotations

import asyncio
import json
import psycopg2
from typing import AsyncGenerator, Optional
from uuid import UUID
from contextlib import asynccontextmanager

from psycopg2.extras import RealDictCursor
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import select, update, text

from .config import settings
from .models import URLIngestionJob


# Create the async SQLAlchemy engine using the DATABASE_URL from settings.
# settings.DATABASE_URL is normalized to start with postgresql+asyncpg:// in config.py.
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)


# Create a session factory for async sessions.
async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an AsyncSession and ensures it is closed after use.

    Use in FastAPI endpoints as: db: AsyncSession = Depends(get_db_session)
    """
    async with async_session() as session:
        yield session


async def create_job(url: str, metadata: Optional[dict] = None) -> URLIngestionJob:
    """Create a new URL ingestion job in the database.

    Args:
        url: URL to ingest.
        metadata: Optional metadata dict.

    Returns:
        The created URLIngestionJob instance (fresh from DB).
    """
    async with async_session() as session:
        job = URLIngestionJob(url=url, status="pending")
        # set mapped metadata column via attribute 'metadata_json'
        job.metadata_json = metadata or {}
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job


async def update_job_status(job_id: UUID, status: str, **kwargs) -> Optional[URLIngestionJob]:
    """Update job fields for a job identified by job_id.

    Any additional kwargs are set as attributes on the model (if present).
    Returns the updated job, or None if not found.
    """
    async with async_session() as session:
        q = await session.execute(select(URLIngestionJob).where(URLIngestionJob.id == job_id))
        job: Optional[URLIngestionJob] = q.scalars().first()
        if not job:
            return None
        job.status = status
        for k, v in kwargs.items():
            # Map incoming 'metadata' key to the metadata_json column attribute
            if k == "metadata":
                setattr(job, "metadata_json", v)
            elif hasattr(job, k):
                setattr(job, k, v)
        await session.commit()
        await session.refresh(job)
        return job


async def get_job_by_id(job_id: UUID) -> Optional[URLIngestionJob]:
    """Fetch a job by its UUID. Returns None if not found."""
    async with async_session() as session:
        q = await session.execute(select(URLIngestionJob).where(URLIngestionJob.id == job_id))
        return q.scalars().first()


async def check_db_health() -> bool:
    """Quick health check against the database. Returns True if reachable."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Synchronous DB helpers (psycopg2) for use from Celery worker processes.
# These avoid creating or reusing asyncio event loops inside Celery worker
# processes, which was causing 'attached to a different loop' errors when
# asyncpg created background tasks.
# ---------------------------------------------------------------------------


def _pg_connect():
    return psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=int(settings.POSTGRES_PORT),
        dbname=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )


def update_job_status_sync(job_id: UUID, status: str, **kwargs) -> Optional[dict]:
    """Synchronous update of a job record using psycopg2.

    Returns the updated row as a dict (or None if no row matched).
    Accepts the same kwargs used by the async version (started_at, completed_at,
    chunk_count, error_message, error_traceback, celery_task_id, metadata).
    """
    set_clauses = ["status = %s"]
    params: list = [status]

    # Known updatable fields
    mapping_fields = {
        "started_at": "started_at",
        "completed_at": "completed_at",
        "chunk_count": "chunk_count",
        "error_message": "error_message",
        "error_traceback": "error_traceback",
        "celery_task_id": "celery_task_id",
        "total_tokens": "total_tokens",
        "processing_time_seconds": "processing_time_seconds",
    }

    for k, col in mapping_fields.items():
        if k in kwargs:
            set_clauses.append(f"{col} = %s")
            params.append(kwargs[k])

    # metadata is stored in column 'metadata'
    if "metadata" in kwargs:
        set_clauses.append("metadata = %s")
        params.append(json.dumps(kwargs["metadata"]))

    params.append(str(job_id))

    sql = f"UPDATE url_ingestion_jobs SET {', '.join(set_clauses)} WHERE id = %s RETURNING *"

    conn = None
    try:
        conn = _pg_connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def get_job_by_id_sync(job_id: UUID) -> Optional[dict]:
    """Synchronous fetch of a job row as a dict."""
    sql = "SELECT * FROM url_ingestion_jobs WHERE id = %s"
    conn = None
    try:
        conn = _pg_connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (str(job_id),))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        if conn:
            conn.close()
