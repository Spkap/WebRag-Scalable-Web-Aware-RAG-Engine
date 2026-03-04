from __future__ import annotations

import time
from typing import List

from google import genai
from google.genai import types

from ..utils.logger import get_logger
from ..config import settings

logger = get_logger(__name__)


class GeminiEmbeddings:
    """Wrapper around the google-genai SDK for Gemini embeddings with retries.

    Uses the unified google-genai SDK (google-generativeai is deprecated).
    Supports true batch embedding — one API call for all chunks in a batch.

    Example:
        embedder = GeminiEmbeddings()
        vectors = embedder.embed_documents(["chunk 1", "chunk 2"])
        query_vec = embedder.embed_query("what is RAG?")
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-embedding-001",
        output_dimensionality: int = 1536,
    ) -> None:
        self.api_key = api_key or settings.GOOGLE_API_KEY
        self.model = model
        self.output_dimensionality = output_dimensionality
        try:
            self.client = genai.Client(api_key=self.api_key)
        except Exception as exc:
            logger.error("Failed to configure Gemini client", extra={"error": str(exc)})
            raise

    def _with_retries(self, func, *args, **kwargs):
        """Retry wrapper with exponential backoff.

        Differentiates rate-limit errors (more retries) from other transient errors.
        Does NOT retry on ValueError/TypeError (programmer errors, not transient).
        """
        attempt = 0
        backoff = 1.0
        max_retries_rate_limit = 5
        max_retries_other = 3

        while True:
            try:
                return func(*args, **kwargs)
            except (ValueError, TypeError):
                # Non-transient errors — don't retry
                raise
            except Exception as exc:
                attempt += 1
                error_str = str(exc).lower()
                is_rate_limit = any(
                    kw in error_str
                    for kw in ("429", "rate limit", "quota exceeded", "resource exhausted")
                )
                max_retries = max_retries_rate_limit if is_rate_limit else max_retries_other

                if attempt >= max_retries:
                    logger.error(
                        "Gemini API failed after retries",
                        extra={"attempts": attempt, "error": str(exc)},
                    )
                    raise

                logger.warning(
                    "Gemini API call failed, retrying",
                    extra={"attempt": attempt, "backoff": backoff, "rate_limit": is_rate_limit},
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of documents in a single batch API call.

        Uses task_type=RETRIEVAL_DOCUMENT as required by Gemini embedding guidance.
        Returns a list of float vectors in the same order as input texts.
        """
        def _call(batch: List[str]) -> List[List[float]]:
            response = self.client.models.embed_content(
                model=self.model,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=self.output_dimensionality,
                ),
            )
            return [emb.values for emb in response.embeddings]

        return self._with_retries(_call, texts)

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query string.

        Uses task_type=RETRIEVAL_QUERY as required by Gemini embedding guidance.
        """
        def _call(query: str) -> List[float]:
            response = self.client.models.embed_content(
                model=self.model,
                contents=query,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=self.output_dimensionality,
                ),
            )
            return response.embeddings[0].values

        return self._with_retries(_call, text)
