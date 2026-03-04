from __future__ import annotations

from typing import Any, Dict, List

from google import genai
from google.genai import types

from ..utils.logger import get_logger

logger = get_logger(__name__)


class GeminiLLM:
    """Wrapper for Google Gemini models using the unified google-genai SDK.

    Provides a thin adapter around the Gemini generation API to produce
    grounded answers from retrieved context chunks.

    Example:
        llm = GeminiLLM(api_key="ABC")
        answer = llm.generate_answer("What is RAG?", context_chunks)

    Args:
        api_key: Gemini API key (required).
        model: Model name to use, defaults to "gemini-2.5-flash".

    Raises:
        ValueError: If the Gemini client fails to initialize.
    """

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        try:
            self.client = genai.Client(api_key=api_key)
            self.model_name = model
            self.generation_config = types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=1024,
                top_p=0.95,
                top_k=1,
            )
            logger.info("Initialized Gemini LLM", extra={"model": model})
        except Exception as error:
            raise ValueError(f"Failed to initialize Gemini: {error}") from error

    def generate_answer(self, question: str, context_chunks: List[Dict[str, Any]]) -> str:
        """Generate a grounded answer using Gemini based on retrieved context.

        Constructs a deterministic prompt containing retrieved context chunks
        and instructs the model to answer using only that context.

        Args:
            question: The user question to answer. Must be non-empty.
            context_chunks: List of dicts each containing 'text', 'source_url', 'score'.

        Returns:
            The generated answer string.

        Raises:
            ValueError: On unrecoverable API errors.
        """
        logger.info("Generating answer", extra={"question_length": len(question), "chunks": len(context_chunks)})

        # Build context block
        formatted_chunks: List[str] = [
            f"Source {idx} ({chunk.get('source_url', 'unknown')}):\n{chunk.get('text', '')}\n"
            for idx, chunk in enumerate(context_chunks, 1)
        ]
        formatted_context = "\n---\n".join(formatted_chunks)

        prompt = f"""You are a helpful AI assistant that answers questions based ONLY on the provided context.

INSTRUCTIONS:
- Read the context sources carefully
- Answer the question using ONLY information from the context
- If the context doesn't contain enough information, say: "I cannot answer this question based on the provided context."
- Cite which source number(s) you used (e.g., "According to Source 1...")
- Be concise but complete
- Do not add information not present in the context

CONTEXT:
{formatted_context}

QUESTION: {question}

ANSWER:"""

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=self.generation_config,
        )

        # Handle safety refusal
        if response.candidates:
            candidate = response.candidates[0]
            finish_reason = getattr(candidate, "finish_reason", None)
            if finish_reason and str(finish_reason).upper() in ("SAFETY", "2"):
                return "I cannot answer this question based on the provided context."

        return (response.text or "").strip()
