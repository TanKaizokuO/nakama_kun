from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from typing import Any


class EmbeddingProvider(ABC):
    """Abstract interface for generating document and query embeddings."""

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of documents."""
        pass

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Generate embedding for a single query string."""
        pass


class LocalEmbeddingProvider(EmbeddingProvider):
    """Local embedding provider utilizing ChromaDB's default or a robust hashing fallback."""

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension
        self._chroma_ef: Any | None = None
        self._use_fallback = False

        # Attempt to load Chroma's default embedding function
        try:
            from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
            # Use ONNX miniLM if possible
            self._chroma_ef = ONNXMiniLM_L6_V2()
            # Test it with a dummy string to see if it downloads and runs successfully
            _ = self._chroma_ef(["test"])
        except Exception:
            # Fall back to deterministic hashing vectorizer (useful for offline/hermetic testing)
            self._use_fallback = True

    def _hash_embed(self, text: str) -> list[float]:
        """Generate a deterministic, process-independent unit vector for a text."""
        import re
        normalized = re.sub(r"[^a-zA-Z0-9\s]", " ", text)
        words = normalized.lower().split()
        if not words:
            # Return a unit vector with 1.0 at index 0
            vec = [0.0] * self.dimension
            vec[0] = 1.0
            return vec

        vec = [0.0] * self.dimension
        for word in words:
            # Process-deterministic hash using MD5
            h = hashlib.md5(word.encode("utf-8")).digest()
            idx = int.from_bytes(h, "big") % self.dimension
            # Use term frequency weighting
            vec[idx] += 1.0

        # Compute L2 norm
        square_sum = sum(val * val for val in vec)
        l2_norm = math.sqrt(square_sum)

        if l2_norm < 1e-9:
            vec[0] = 1.0
            return vec

        # L2 normalize
        return [val / l2_norm for val in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._use_fallback or self._chroma_ef is None:
            return [self._hash_embed(text) for text in texts]

        try:
            return self._chroma_ef(texts)  # type: ignore
        except Exception:
            # Fall back dynamically if runtime download/execution fails
            return [self._hash_embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI/OpenRouter embedding provider using the OpenAI SDK."""

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        model: str = "text-embedding-3-small",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self._client

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=texts,
            )
            # Sort by index to preserve order
            data = sorted(response.data, key=lambda x: x.index)
            return [item.embedding for item in data]
        except Exception as exc:
            from loguru import logger
            logger.error(f"OpenAI embedding request failed: {exc}")
            raise

    def embed_query(self, text: str) -> list[float]:
        res = self.embed_documents([text])
        if not res:
            raise ValueError("Empty response received from embedding provider")
        return res[0]
