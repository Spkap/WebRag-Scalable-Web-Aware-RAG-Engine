from __future__ import annotations

import traceback
from datetime import datetime
from typing import Dict, List
from uuid import UUID

from celery import Task

from ..celery_app import celery_app
from ..config import settings
from ..database import update_job_status_sync, get_job_by_id_sync
from ..services.content_processor import ContentProcessor
from ..services.embeddings import GeminiEmbeddings
from ..services.vectorstore import QdrantStore
from ..utils.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(bind=True, name="app.tasks.ingestion.process_url_ingestion", max_retries=3)
def process_url_ingestion(self: Task, job_id: str, url: str) -> Dict:
    """Background task to fetch a URL, chunk, embed and store vectors.

    Steps:
    1. Mark job processing
    2. Fetch content
    3. Clean and chunk text
    4. Generate embeddings (batching)
    5. Upsert to Qdrant
    6. Mark job completed

    On error will attempt retries with exponential backoff and ultimately mark
    the job as failed with the error details.
    """

    logger.info("Starting ingestion task", extra={"job_id": job_id, "url": url})

    def _work(jid: str, u: str) -> Dict:
        logger.info("Converting job_id to UUID", extra={"job_id": jid})
        jid_uuid = UUID(jid)

        logger.info("Marking job as processing", extra={"job_id": jid})
        # Mark processing
        update_job_status_sync(jid_uuid, "processing", started_at=datetime.utcnow())

        logger.info("Fetching URL content", extra={"url": u})
        # 1. Fetch
        html = ContentProcessor.fetch_url_content_sync(u)

        logger.info("Cleaning HTML", extra={"content_length": len(html)})
        # 2. Clean
        text = ContentProcessor.clean_html(html)

        logger.info("Chunking text", extra={"text_length": len(text)})
        # 3. Chunk
        chunks = ContentProcessor.chunk_text(text, chunk_size=settings.CHUNK_SIZE, chunk_overlap=settings.CHUNK_OVERLAP)

        logger.info("Generating embeddings", extra={"num_chunks": len(chunks)})
        # 4. Embeddings (batch)
        embedder = GeminiEmbeddings(api_key=settings.GOOGLE_API_KEY, model=settings.EMBEDDING_MODEL, output_dimensionality=settings.EMBEDDING_DIMENSIONS)
        vectors: List[List[float]] = []
        batch_size = 100
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            batch_vecs = embedder.embed_documents(batch)
            vectors.extend(batch_vecs)

        logger.info("Storing in Qdrant", extra={"num_vectors": len(vectors)})
        # 5. Qdrant upsert
        store = QdrantStore(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, collection_name=settings.QDRANT_COLLECTION)
        store.create_collection_if_not_exists()
        metadata = {"source_url": u}
        added = store.add_documents(chunks=chunks, vectors=vectors, metadata=metadata, job_id=jid)

        logger.info("Marking job as completed", extra={"chunks_added": added})
        # 6. Completed
        update_job_status_sync(jid_uuid, "completed", chunk_count=len(chunks), completed_at=datetime.utcnow())
        return {"job_id": jid, "status": "completed", "chunks_added": added}

    try:
        # Run the work in a separate thread to avoid event loop conflicts
        import threading
        result = None
        exception = None
        
        def run_work():
            nonlocal result, exception
            try:
                result = _work(job_id, url)
            except Exception as e:
                exception = e
        
        thread = threading.Thread(target=run_work)
        thread.start()
        thread.join(timeout=300)  # 5 minute timeout
        
        if thread.is_alive():
            raise TimeoutError("Ingestion task timed out")
        if exception:
            raise exception
            
        logger.info("Ingestion task completed", extra={"job_id": job_id})
        return result
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("Ingestion task failed", extra={"job_id": job_id, "error": str(exc), "traceback": tb})

        # Attempt to mark job as failed
        try:
            update_job_status_sync(UUID(job_id), "failed", error_message=str(exc), error_traceback=tb)
        except Exception as e2:
            logger.error("Failed to persist job failure", extra={"job_id": job_id, "error": str(e2)})

        # Decide whether to retry
        retries = getattr(self.request, "retries", 0) if hasattr(self, "request") else 0
        if retries < self.max_retries:
            countdown = 60 * (2 ** retries)
            logger.info("Retrying ingestion task", extra={"job_id": job_id, "countdown": countdown, "retries": retries})
            raise self.retry(exc=exc, countdown=countdown)

        # No more retries
        raise
