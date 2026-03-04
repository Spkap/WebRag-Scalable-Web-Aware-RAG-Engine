from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from ..utils.logger import get_logger
from ..config import settings

logger = get_logger(__name__)


class QdrantStore:
    """Simple wrapper around QdrantClient for our use-case.

    This class intentionally keeps a small surface area: create collection,
    upsert points, and run vector search queries.
    """

    def __init__(self, host: str, port: int, collection_name: str) -> None:
        # Disable client/server compatibility check to handle minor server/client
        # version mismatches in development environments. For production, align
        # client and server versions and consider removing this flag.
        try:
            self.client = QdrantClient(host=host, port=port, check_compatibility=False)
        except TypeError:
            # Older qdrant-client versions may not accept check_compatibility; fall back.
            self.client = QdrantClient(host=host, port=port)
        self.collection_name = collection_name

    def create_collection_if_not_exists(self) -> None:
        try:
            # Try to fetch collection; if it does not exist an exception is raised.
            _ = self.client.get_collection(self.collection_name)
            logger.info("Qdrant collection exists", extra={"collection": self.collection_name})
        except Exception:
            logger.info("Creating Qdrant collection", extra={"collection": self.collection_name})
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=settings.EMBEDDING_DIMENSIONS, distance=Distance.COSINE),
            )

    def add_documents(self, chunks: List[str], vectors: List[List[float]], metadata: Dict, job_id: str) -> int:
        """Upsert document chunks as points into the Qdrant collection.

        Returns the number of points added.
        """
        points: List[PointStruct] = []
        ingested_at = datetime.utcnow().isoformat()
        for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
            payload = {
                "text": chunk,
                "source_url": metadata.get("source_url") if metadata else None,
                "job_id": job_id,
                "chunk_index": idx,
                "ingested_at": ingested_at,
                "title": metadata.get("title") if metadata else None,
            }
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{job_id}-{idx}"))
            points.append(PointStruct(id=point_id, vector=vec, payload=payload))

        try:
            self.client.upsert(collection_name=self.collection_name, points=points)
            return len(points)
        except Exception as exc:
            logger.error("Failed to upsert points to Qdrant", extra={"error": str(exc)})
            raise

    def search(self, query_vector: List[float], top_k: int = 5, filters: Optional[Dict] = None) -> List[Dict]:
        """Search Qdrant and return simplified result dicts containing text, source_url and score."""
        try:
            # Convert filters dict to Qdrant filter format
            query_filter = None
            if filters:
                must_conditions = []
                for key, value in filters.items():
                    must_conditions.append({
                        "key": key,
                        "match": {"value": value}
                    })
                query_filter = {"must": must_conditions}
            
            hits = self.client.search(collection_name=self.collection_name, query_vector=query_vector, limit=top_k, query_filter=query_filter)
            results: List[Dict] = []
            for h in hits:
                payload = h.payload or {}
                results.append({"text": payload.get("text"), "source_url": payload.get("source_url"), "score": getattr(h, "score", None) or getattr(h, "distance", None)})
            return results
        except Exception as exc:
            logger.error("Qdrant search failed", extra={"error": str(exc)})
            raise


def ensure_qdrant_collection(collection_name: str | None = None) -> None:
    """Ensure the Qdrant collection exists with the correct vector size and distance metric.

    This helper is intentionally synchronous and safe to call from startup code
    via run_in_threadpool.
    """
    collection = collection_name or "web_documents"
    # Try to connect to Qdrant and create the collection, with retries to handle
    # race conditions where Qdrant is still starting when the API starts.
    attempts = 0
    max_attempts = 6
    backoff = 1.0
    last_exc: Exception | None = None
    while attempts < max_attempts:
        try:
            try:
                client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, check_compatibility=False)
            except TypeError:
                client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)

            # Check if collection exists and create if missing
            try:
                _ = client.get_collection(collection_name=collection)
                logger.info("Qdrant collection exists", extra={"collection": collection})
                return
            except Exception:
                # Collection doesn't exist, try to create it
                try:
                    logger.info("Creating Qdrant collection", extra={"collection": collection})
                    client.create_collection(collection_name=collection, vectors_config=VectorParams(size=settings.EMBEDDING_DIMENSIONS, distance=Distance.COSINE))
                    logger.info("Qdrant collection created successfully", extra={"collection": collection})
                except Exception as create_exc:
                    # Check if it's just "already exists" error, which is fine
                    error_str = str(create_exc).lower()
                    if "already exists" in error_str or "400" in error_str:
                        logger.info("Qdrant collection already exists (created by another process)", extra={"collection": collection})
                    else:
                        # Re-raise if it's a real error
                        raise create_exc
            return
        except Exception as exc:
            last_exc = exc
            attempts += 1
            logger.warning("Qdrant unavailable, retrying", extra={"attempt": attempts, "error": str(exc)})
            import time

            time.sleep(backoff)
            backoff = min(backoff * 2, 10.0)

    # If we exhausted retries, raise the last exception so callers can decide.
    logger.error("Failed to ensure Qdrant collection after retries", extra={"error": str(last_exc)})
    if last_exc:
        raise last_exc
