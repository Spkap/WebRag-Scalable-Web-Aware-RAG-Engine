from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict
from datetime import datetime
from uuid import UUID

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    status as http_status,
)
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

import redis as redis_lib
import time
from qdrant_client import QdrantClient

from .config import settings
from .services.embeddings import GeminiEmbeddings
from .services.vectorstore import QdrantStore
from .services.llm import GeminiLLM
from .utils.logger import get_logger
from .celery_app import celery_app
from .models import (
    IngestURLRequest,
    IngestURLResponse,
    JobStatusResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    SourceChunk,
)
from .database import (
    create_job,
    update_job_status,
    get_job_by_id,
    check_db_health,
)
from .utils.validators import is_valid_url

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared RAG services once on startup; clean up on shutdown."""
    logger.info("Starting WebRAG API", extra={"port": settings.API_PORT})

    # Instantiate services once — reused across all requests (no per-request overhead)
    app.state.embedder = GeminiEmbeddings(
        api_key=settings.GOOGLE_API_KEY,
        model=settings.EMBEDDING_MODEL,
        output_dimensionality=settings.EMBEDDING_DIMENSIONS,
    )
    app.state.vectorstore = QdrantStore(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        collection_name=settings.QDRANT_COLLECTION,
    )
    app.state.llm = GeminiLLM(api_key=settings.GOOGLE_API_KEY, model="gemini-2.5-flash")

    # Ensure Qdrant collection exists (sync client wrapped in threadpool)
    try:
        from .services.vectorstore import ensure_qdrant_collection
        await run_in_threadpool(ensure_qdrant_collection)
        logger.info("Qdrant collection ensured")
    except Exception as exc:
        logger.warning("Failed to ensure Qdrant collection on startup", extra={"error": str(exc)})

    yield  # Application runs here

    logger.info("WebRAG API shutting down")


app = FastAPI(
    title="WebRAG API",
    version="1.0.0",
    description="Scalable Web-Aware RAG Engine",
    lifespan=lifespan,
)


# Development/demo CORS policy - allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log incoming requests and their duration."""
    logger.info("incoming request", extra={"method": request.method, "path": request.url.path})
    start = datetime.utcnow()
    try:
        response = await call_next(request)
    except Exception as exc:  # Ensure we log exceptions
        logger.exception("request handler raised", extra={"path": request.url.path})
        raise
    duration = (datetime.utcnow() - start).total_seconds()
    logger.info("request complete", extra={"method": request.method, "path": request.url.path, "status_code": response.status_code, "duration": duration})
    return response


@app.get("/", status_code=http_status.HTTP_200_OK)
async def root() -> Dict[str, Any]:
    """Root endpoint with basic information and a pointer to the OpenAPI docs."""
    return {"message": "Welcome to WebRAG API", "version": app.version, "docs": "/docs"}


@app.post("/ingest-url", response_model=IngestURLResponse, status_code=http_status.HTTP_202_ACCEPTED)
async def ingest_url(request: IngestURLRequest) -> IngestURLResponse:
    """Create an ingestion job and enqueue a Celery task to process the URL.

    This endpoint performs lightweight validation, creates a DB record with status 'pending',
    and enqueues a background Celery task that performs the heavy work.
    """
    # Validate URL
    if not is_valid_url(str(request.url)):
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Invalid URL provided")

    try:
        # Create DB job with status 'pending'
        job = await create_job(str(request.url), metadata=request.metadata or {})
    except Exception as exc:
        logger.exception("Failed to create ingestion job in DB")
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create job")

    # Enqueue Celery task and attach job id so the task updates the same row
    try:
        logger.info("Sending Celery task for URL ingestion", extra={"job_id": str(job.id), "url": str(request.url)})
        async_result = celery_app.send_task("app.tasks.ingestion.process_url_ingestion", args=[str(job.id), str(request.url)])
        logger.info("Celery task sent successfully", extra={"task_id": async_result.id})
        # Persist celery task id on the job
        await update_job_status(job.id, job.status, celery_task_id=async_result.id)
    except Exception as exc:
        logger.exception("Failed to enqueue Celery task")
        # best-effort mark job as failed
        await update_job_status(job.id, "failed", error_message=str(exc))
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to enqueue ingestion task")

    return IngestURLResponse(job_id=job.id, status=job.status, message="Job accepted", estimated_time_seconds=30)


@app.post("/query", response_model=QueryResponse, status_code=http_status.HTTP_200_OK)
async def query_knowledge_base(
    body: QueryRequest,
    http_request: Request,
) -> QueryResponse:
    """Query the ingested knowledge base using a RAG pipeline.

    This endpoint implements the complete RAG query flow:
    1. Embeds user question using Gemini (1536-dim)
    2. Searches Qdrant vector database for similar chunks (top_k)
    3. Passes question + retrieved chunks to Gemini for answer generation
    4. Returns grounded answer with source attribution

    Args:
        body: QueryRequest containing question, optional top_k and filters
        http_request: FastAPI Request (used to access shared app.state services)

    Returns:
        QueryResponse with answer, sources list, and metadata

    Raises:
        HTTPException 400: Invalid or empty question
        HTTPException 404: No relevant documents found in database
        HTTPException 500: Internal processing errors (embedding, search, LLM)
    """
    start_time = time.time()
    logger.info("Query received", extra={"question_preview": body.question[:100]})

    try:
        # Reuse singleton services initialised at startup — no per-request construction overhead
        embedder = http_request.app.state.embedder
        vectorstore = http_request.app.state.vectorstore
        llm = http_request.app.state.llm

        # STEP 1: EMBED USER QUESTION
        try:
            query_vector = embedder.embed_query(body.question)
        except Exception as e:
            logger.error("Embedding failed", extra={"error": str(e)})
            raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to embed question: {str(e)}")

        # Validate vector dimension
        if not query_vector or len(query_vector) != settings.EMBEDDING_DIMENSIONS:
            logger.error("Invalid embedding dimension", extra={"got": len(query_vector) if query_vector else 0, "expected": settings.EMBEDDING_DIMENSIONS})
            raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Embedding service returned invalid dimension")

        logger.info("Query embedded", extra={"dimension": len(query_vector)})

        # STEP 2: SEARCH QDRANT FOR SIMILAR CHUNKS
        try:
            search_results = vectorstore.search(query_vector=query_vector, top_k=body.top_k, filters=body.filters)
        except Exception as e:
            logger.error("Vector search failed", extra={"error": str(e)})
            raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Vector database search failed: {str(e)}")

        if not search_results:
            logger.warning("No documents found in vector database")
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="No relevant documents found. Please ingest URLs first using POST /ingest-url")

        logger.info("Chunks retrieved", extra={"count": len(search_results)})

        # STEP 3: GENERATE ANSWER USING GEMINI
        try:
            answer = llm.generate_answer(question=body.question, context_chunks=search_results)
        except ValueError as e:
            logger.error("LLM generation error", extra={"error": str(e)})
            raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Answer generation failed: {str(e)}")
        except Exception as e:
            logger.error("Unexpected LLM error", extra={"error": str(e)}, exc_info=True)
            raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate answer due to internal error")

        logger.info("Answer generated", extra={"answer_length": len(answer)})

        # STEP 4: FORMAT RESPONSE WITH SOURCES
        sources = []
        for result in search_results:
            txt = result.get('text') or ""
            if len(txt) > 300:
                txt = txt[:300] + "..."
            sources.append(
                {
                    "text": txt,
                    "source_url": result.get('source_url'),
                    "relevance_score": round(float(result.get('score') or 0.0), 4),
                }
            )

        processing_time_ms = int((time.time() - start_time) * 1000)

        metadata = {
            "chunks_retrieved": len(search_results),
            "processing_time_ms": processing_time_ms,
            "embedding_model": settings.EMBEDDING_MODEL,
            "llm_model": "gemini-2.5-flash",
            "top_k": body.top_k,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        source_objs = [
            SourceChunk(text=s["text"], source_url=s["source_url"], relevance_score=s["relevance_score"]) for s in sources
        ]

        response = QueryResponse(answer=answer, sources=source_objs, metadata=metadata)

        logger.info("Query completed", extra={"processing_time_ms": processing_time_ms})
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected query pipeline error", extra={"error": str(e)}, exc_info=True)
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Query processing failed: {str(e)}")


@app.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_status(job_id: UUID) -> JobStatusResponse:
    """Return the ingestion job status and metadata for a given job_id."""
    job = await get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job not found")

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        url=job.url,
        created_at=job.created_at,
        completed_at=job.completed_at,
        processing_time_seconds=job.processing_time_seconds,
        chunk_count=job.chunk_count or 0,
        error_message=job.error_message,
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health endpoint that checks connectivity to Postgres, Redis, Qdrant and Celery workers.

    Returns overall status=ok when all components are reachable; otherwise status=degraded.
    """
    services: Dict[str, Any] = {}

    # DB
    db_ok = await check_db_health()
    services["postgres"] = {"ok": db_ok}

    # Redis (sync client wrapped in threadpool)
    try:
        def _redis_ping() -> bool:
            r = redis_lib.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0, socket_connect_timeout=1)
            return r.ping()

        redis_ok = await run_in_threadpool(_redis_ping)
    except Exception:
        redis_ok = False
    services["redis"] = {"ok": redis_ok}

    # Qdrant
    try:
        def _qdrant_check() -> bool:
            client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
            _ = client.get_collections()
            return True

        qdrant_ok = await run_in_threadpool(_qdrant_check)
    except Exception:
        qdrant_ok = False
    services["qdrant"] = {"ok": qdrant_ok}

    # Celery workers
    try:
        inspector = celery_app.control.inspect(timeout=1.0)
        active = inspector.ping() or {}
        workers = list(active.keys()) if isinstance(active, dict) else []
        celery_ok = len(workers) > 0
    except Exception:
        celery_ok = False
        workers = []
    services["celery"] = {"ok": celery_ok, "workers": workers}

    overall_ok = all(v["ok"] for v in services.values())
    status_text = "ok" if overall_ok else "degraded"

    return HealthResponse(status=status_text, services=services, timestamp=datetime.utcnow(), version=app.version)


# Exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning("HTTP error", extra={"path": request.url.path, "detail": exc.detail})
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception", extra={"path": request.url.path})
    return JSONResponse(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": str(exc)})
