from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch
import pytest

from nakama_kun.config.rag import RAGSettings
from nakama_kun.rag import get_retriever, reset_rag_caches
from nakama_kun.rag.model_manager import (
    preload_rag_models,
    reset_cached_models,
    load_bgem3_model,
    load_reranker_model,
    load_onnx_model,
)
from nakama_kun.rag.embeddings import BGEM3EmbeddingProvider
from nakama_kun.rag.retriever import BGEReranker


@pytest.fixture(autouse=True)
def clean_caches():
    reset_rag_caches()
    reset_cached_models()
    yield
    reset_rag_caches()
    reset_cached_models()


def test_model_loading_occurs_once():
    # Mock SentenceTransformer, CrossEncoder and ONNXMiniLM
    mock_st_class = MagicMock()
    mock_ce_class = MagicMock()
    mock_onnx_class = MagicMock()

    with patch("sentence_transformers.SentenceTransformer", mock_st_class), \
         patch("sentence_transformers.CrossEncoder", mock_ce_class), \
         patch("chromadb.utils.embedding_functions.ONNXMiniLM_L6_V2", mock_onnx_class):

        # Load models first time
        model1 = load_bgem3_model()
        reranker1 = load_reranker_model()
        onnx1 = load_onnx_model()

        # Load models second time
        model2 = load_bgem3_model()
        reranker2 = load_reranker_model()
        onnx2 = load_onnx_model()

        # Assert called exactly once
        assert mock_st_class.call_count == 1
        assert mock_ce_class.call_count == 1
        assert mock_onnx_class.call_count == 1

        # Assert same instances returned
        assert model1 is model2
        assert reranker1 is reranker2
        assert onnx1 is onnx2


def test_get_retriever_reuses_instances(tmp_path):
    # We want to check that multiple get_retriever calls return the same Retriever instance
    # Create a dummy .rag directory so get_retriever doesn't fail gracefully (checks path exists)
    db_dir = tmp_path / ".rag"
    db_dir.mkdir(parents=True, exist_ok=True)
    
    with patch.dict("os.environ", {"RAG_ENABLED": "True", "RAG_DB_PATH": str(db_dir)}):
        ret1 = get_retriever(str(tmp_path))
        ret2 = get_retriever(str(tmp_path))
        
        assert ret1 is not None
        assert ret2 is not None
        assert ret1 is ret2


def test_preload_rag_models_preloads_successfully():
    mock_st_class = MagicMock()
    mock_ce_class = MagicMock()

    with patch("sentence_transformers.SentenceTransformer", mock_st_class), \
         patch("sentence_transformers.CrossEncoder", mock_ce_class):

        preload_rag_models()

        assert mock_st_class.call_count == 1
        assert mock_ce_class.call_count == 1


def test_hashing_fallback_does_not_load_models_when_fallback_forced():
    mock_st_class = MagicMock()
    mock_ce_class = MagicMock()

    with patch("sentence_transformers.SentenceTransformer", mock_st_class), \
         patch("sentence_transformers.CrossEncoder", mock_ce_class):

        provider = BGEM3EmbeddingProvider(use_fallback=True)
        reranker = BGEReranker(use_fallback=True)

        assert mock_st_class.call_count == 0
        assert mock_ce_class.call_count == 0
        assert provider._model is None
        assert reranker._model is None
