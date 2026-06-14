from __future__ import annotations

import threading
from typing import Any
from loguru import logger

_bgem3_model: Any | None = None
_bgem3_lock = threading.Lock()
_bgem3_loaded = False

_reranker_model: Any | None = None
_reranker_lock = threading.Lock()
_reranker_loaded = False

_onnx_model: Any | None = None
_onnx_lock = threading.Lock()
_onnx_loaded = False

_ready_printed = False


def load_bgem3_model() -> Any:
    """Load BGE-M3 model thread-safely exactly once."""
    global _bgem3_model, _bgem3_loaded
    if _bgem3_loaded:
        return _bgem3_model

    with _bgem3_lock:
        if not _bgem3_loaded:
            print("[RAG] Loading BGE-M3 model...", flush=True)
            logger.info("[RAG] Loading BGE-M3 model...")
            try:
                from sentence_transformers import SentenceTransformer
                _bgem3_model = SentenceTransformer("BAAI/bge-m3")
            except Exception as e:
                logger.warning(
                    f"sentence-transformers not installed or BGE-M3 model failed to load locally. "
                    f"Falling back to deterministic hashing vectorizer (dimension 1024). Error: {e}"
                )
                _bgem3_model = None
            _bgem3_loaded = True
            _check_ready()
    return _bgem3_model


def load_reranker_model() -> Any:
    """Load BGE Reranker model thread-safely exactly once."""
    global _reranker_model, _reranker_loaded
    if _reranker_loaded:
        return _reranker_model

    with _reranker_lock:
        if not _reranker_loaded:
            print("[RAG] Loading BGE reranker...", flush=True)
            logger.info("[RAG] Loading BGE reranker...")
            try:
                from sentence_transformers import CrossEncoder
                _reranker_model = CrossEncoder("BAAI/bge-reranker-base")
            except Exception as e:
                logger.warning(
                    f"sentence-transformers not installed or BGE-Reranker failed to load. "
                    f"Falling back to deterministic lexical reranking. Error: {e}"
                )
                _reranker_model = None
            _reranker_loaded = True
            _check_ready()
    return _reranker_model


def load_onnx_model() -> Any:
    """Load ONNX fallback model thread-safely exactly once."""
    global _onnx_model, _onnx_loaded
    if _onnx_loaded:
        return _onnx_model

    with _onnx_lock:
        if not _onnx_loaded:
            logger.info("[RAG] Loading ONNX fallback model...")
            try:
                from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
                _onnx_model = ONNXMiniLM_L6_V2()
                # Test it with a dummy string
                _ = _onnx_model(["test"])
            except Exception as e:
                logger.warning(f"Failed to load ONNX model: {e}")
                _onnx_model = None
            _onnx_loaded = True
    return _onnx_model


def _check_ready() -> None:
    """Check if the required models are ready and log a completion message exactly once."""
    global _ready_printed
    if _ready_printed:
        return

    from nakama_kun.config.rag import RAGSettings
    try:
        settings = RAGSettings()
        provider_type = settings.rag_embedding_provider.lower()
        needs_bgem3 = provider_type not in ("openai", "openrouter")
    except Exception:
        # Fallback to local BGEM3 defaults
        needs_bgem3 = True

    bgem3_ok = (not needs_bgem3) or _bgem3_loaded
    reranker_ok = _reranker_loaded

    if bgem3_ok and reranker_ok:
        print("[RAG] Models ready.", flush=True)
        logger.info("[RAG] Models ready.")
        _ready_printed = True


def preload_rag_models() -> None:
    """Eagerly load BGE-M3 and/or Reranker models at application startup."""
    from nakama_kun.config.rag import RAGSettings
    try:
        settings = RAGSettings()
        if not settings.rag_enabled:
            return

        provider_type = settings.rag_embedding_provider.lower()
        needs_bgem3 = provider_type not in ("openai", "openrouter")

        if needs_bgem3:
            load_bgem3_model()

        # Reranker is always local BGE reranker
        load_reranker_model()
    except Exception as e:
        logger.error(f"Failed to preload RAG models: {e}")


def reset_cached_models() -> None:
    """Reset cached models (mostly for unit testing)."""
    global _bgem3_model, _bgem3_loaded, _reranker_model, _reranker_loaded, _onnx_model, _onnx_loaded, _ready_printed
    with _bgem3_lock:
        _bgem3_model = None
        _bgem3_loaded = False
    with _reranker_lock:
        _reranker_model = None
        _reranker_loaded = False
    with _onnx_lock:
        _onnx_model = None
        _onnx_loaded = False
    _ready_printed = False
