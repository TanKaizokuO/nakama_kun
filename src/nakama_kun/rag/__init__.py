from __future__ import annotations

import os
import threading

from nakama_kun.config.rag import RAGSettings
from nakama_kun.rag.embeddings import (
    EmbeddingProvider,
    LocalEmbeddingProvider,
    OpenAIEmbeddingProvider,
    BGEM3EmbeddingProvider,
)
from nakama_kun.rag.indexer import Indexer
from nakama_kun.rag.retriever import Retriever
from nakama_kun.rag.vector_store import ChromaVectorStore, DocumentChunk, VectorStore

_embedding_provider_cache: EmbeddingProvider | None = None
_embedding_provider_lock = threading.Lock()

_vector_store_cache: dict[str, VectorStore] = {}
_vector_store_lock = threading.Lock()

_retriever_cache: dict[str, Retriever] = {}
_retriever_lock = threading.Lock()


def reset_rag_caches() -> None:
    """Reset cached provider, vector store, and retriever instances (mostly for testing)."""
    global _embedding_provider_cache, _vector_store_cache, _retriever_cache
    with _embedding_provider_lock:
        _embedding_provider_cache = None
    with _vector_store_lock:
        _vector_store_cache.clear()
    with _retriever_lock:
        _retriever_cache.clear()


def get_embedding_provider(settings: RAGSettings) -> EmbeddingProvider:
    """Instantiate the configured embedding provider, mapping settings to providers."""
    global _embedding_provider_cache
    if _embedding_provider_cache is not None:
        return _embedding_provider_cache

    with _embedding_provider_lock:
        if _embedding_provider_cache is None:
            provider_type = settings.rag_embedding_provider.lower()
            if provider_type in ("openai", "openrouter"):
                api_key = settings.rag_embedding_api_key
                # Fall back to general OpenRouter config if RAG credentials are blank
                if not api_key:
                    from nakama_kun.ai.config import AISettings
                    ai_settings = AISettings()
                    if ai_settings.openrouter_api_key:
                        api_key = ai_settings.openrouter_api_key.get_secret_value()

                base_url = settings.rag_embedding_base_url
                if not base_url and provider_type == "openrouter":
                    from nakama_kun.ai.config import AISettings
                    ai_settings = AISettings()
                    base_url = ai_settings.openrouter_base_url

                if not api_key:
                    from loguru import logger
                    logger.warning("RAG embedding API key not found. Falling back to local BGEM3 embedding provider.")
                    _embedding_provider_cache = BGEM3EmbeddingProvider()
                else:
                    _embedding_provider_cache = OpenAIEmbeddingProvider(
                        api_key=api_key,
                        base_url=base_url,
                        model=settings.rag_embedding_model,
                    )
            else:
                _embedding_provider_cache = BGEM3EmbeddingProvider()
        return _embedding_provider_cache


def get_vector_store(workspace_root: str | None = None) -> VectorStore | None:
    """Instantiate and return the configured vector store, or None if disabled."""
    settings = RAGSettings()
    if not settings.rag_enabled:
        return None

    root = workspace_root or os.getcwd()
    db_path = settings.rag_db_path
    if not os.path.isabs(db_path):
        db_path = os.path.join(root, db_path)

    global _vector_store_cache
    if root in _vector_store_cache:
        return _vector_store_cache[root]

    with _vector_store_lock:
        if root not in _vector_store_cache:
            provider = get_embedding_provider(settings)
            _vector_store_cache[root] = ChromaVectorStore(
                db_path=db_path,
                embedding_provider=provider,
            )
        return _vector_store_cache[root]


def get_indexer(workspace_root: str | None = None) -> Indexer | None:
    """Instantiate and return the workspace indexer, or None if disabled."""
    settings = RAGSettings()
    if not settings.rag_enabled:
        return None

    root = workspace_root or os.getcwd()
    store = get_vector_store(root)
    if store is None:
        return None

    return Indexer(
        workspace_root=root,
        vector_store=store,
        chunk_size_lines=settings.rag_chunk_size_lines,
        chunk_overlap_lines=settings.rag_chunk_overlap_lines,
    )


def get_retriever(workspace_root: str | None = None) -> Retriever | None:
    """Instantiate and return the retriever, or None if disabled or if index does not exist."""
    settings = RAGSettings()
    if not settings.rag_enabled:
        return None

    root = workspace_root or os.getcwd()
    db_path = settings.rag_db_path
    if not os.path.isabs(db_path):
        db_path = os.path.join(root, db_path)

    # Fail gracefully if index has not been built yet (retrieval is optional)
    if not os.path.exists(db_path):
        return None

    global _retriever_cache
    if root in _retriever_cache:
        return _retriever_cache[root]

    with _retriever_lock:
        if root not in _retriever_cache:
            store = get_vector_store(root)
            if store is None:
                return None
            _retriever_cache[root] = Retriever(vector_store=store)
        return _retriever_cache[root]


__all__ = [
    "EmbeddingProvider",
    "LocalEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "BGEM3EmbeddingProvider",
    "DocumentChunk",
    "VectorStore",
    "ChromaVectorStore",
    "Indexer",
    "Retriever",
    "get_embedding_provider",
    "get_vector_store",
    "get_indexer",
    "get_retriever",
    "reset_rag_caches",
]
