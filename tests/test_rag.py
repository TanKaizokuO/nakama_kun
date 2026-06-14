from __future__ import annotations

import os
import shutil
import sqlite3
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nakama_kun.rag import get_vector_store, get_indexer
from nakama_kun.rag.embeddings import BGEM3EmbeddingProvider
from nakama_kun.rag.indexer import Indexer, chunk_text
from nakama_kun.rag.vector_store import ChromaVectorStore, DocumentChunk, IndexedDocument


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    # Set up temp workspace directory
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def mock_embedding_provider() -> BGEM3EmbeddingProvider:
    # Force the fallback 1024-dimensional hashing path to run predictably
    provider = BGEM3EmbeddingProvider(use_fallback=True)
    return provider


@pytest.fixture
def clean_rag_settings(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_ENABLED", "True")
    monkeypatch.setenv("RAG_DB_PATH", str(temp_workspace / ".rag"))
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "local")


def test_bgem3_hashing_fallback_properties(mock_embedding_provider: BGEM3EmbeddingProvider) -> None:
    # 1. Dimension is 1024
    assert mock_embedding_provider.dimension == 1024

    # 2. Deterministic
    vec1 = mock_embedding_provider.embed_query("hello world")
    vec2 = mock_embedding_provider.embed_query("hello world")
    assert vec1 == vec2
    assert len(vec1) == 1024

    # 3. Normalized (L2 norm is 1.0)
    norm = sum(x * x for x in vec1)
    assert abs(norm - 1.0) < 1e-5

    # 4. Differentiates content
    vec3 = mock_embedding_provider.embed_query("different code snippet")
    assert vec1 != vec3


def test_character_based_chunk_generation() -> None:
    # Create content that spans multiple chunks
    # We want to check chunk sizes (800-1200 chars) and overlap (100-200 chars)
    paragraph_1 = "A" * 900
    paragraph_2 = "B" * 500
    content = f"# Section One\n{paragraph_1}\n## Section Two\n{paragraph_2}"

    def mock_extractor(lines: list[str], lang: str) -> list[str]:
        return ["symbol1"]

    chunks = chunk_text(
        content=content,
        source_path="doc.md",
        source_type="markdown",
        symbol_extractor=mock_extractor,
        metadata_base={"mtime": "2026-06-14T12:00:00"}
    )

    # Validate output
    assert len(chunks) >= 2
    for chunk in chunks:
        # Each chunk content size should be within bounds or a valid leftover
        assert len(chunk.content) <= 1200
        assert chunk.source_path == "doc.md"
        assert chunk.source_type == "markdown"
        assert chunk.metadata["path"] == "doc.md"
        assert chunk.metadata["document_type"] == "markdown"
        assert "mtime" in chunk.metadata

    # Check section title extraction
    assert chunks[0].metadata["section_title"] == "Section One"
    assert chunks[-1].metadata["section_title"] == "Section Two"
    assert "symbol1" in chunks[0].metadata["symbol_names"]


def test_indexer_incremental_sync_and_persistence(temp_workspace: Path, mock_embedding_provider: BGEM3EmbeddingProvider) -> None:
    # Configure vector store path inside our temp workspace
    rag_dir = temp_workspace / ".rag"
    chroma_dir = rag_dir / "chroma"
    vector_store = ChromaVectorStore(
        db_path=str(chroma_dir),
        embedding_provider=mock_embedding_provider,
    )
    
    indexer = Indexer(
        workspace_root=str(temp_workspace),
        vector_store=vector_store,
    )

    # Create test files
    unmodified_file = temp_workspace / "unmodified.py"
    unmodified_file.write_text("def run_unmodified():\n    return 'unmodified'" + " "*800) # Ensure size > 800

    modified_file = temp_workspace / "modified.py"
    modified_file.write_text("def run_modified():\n    return 'modified'" + " "*800)

    deleted_file = temp_workspace / "deleted.py"
    deleted_file.write_text("def run_deleted():\n    return 'deleted'" + " "*800)

    # 1. Run Clean Build
    indexer.build()

    # Assert persistence directories exist
    assert rag_dir.exists()
    assert chroma_dir.exists()
    assert indexer.sqlite_db_path.exists()
    assert indexer.metadata_path.exists()

    # Assert database files contain correct counts
    docs = indexer.metadata_store.list_documents()
    assert len(docs) == 3
    assert {doc.path for doc in docs} == {"unmodified.py", "modified.py", "deleted.py"}
    
    # Assert Chroma has chunks
    assert vector_store.collection.count() == 3

    # Assert index_metadata.json is populated
    meta = indexer.metadata_manager.load()
    assert meta["embedding_model"] == "BGE-M3"
    assert meta["total_documents"] == 3

    # 2. Modify one file, delete one, keep one unmodified
    # Delete 'deleted.py'
    deleted_file.unlink()

    # Modify 'modified.py'
    # Wait a bit to ensure mtime increases
    import time
    time.sleep(0.1)
    modified_file.write_text("def run_modified():\n    return 'modified_updated_content'" + " "*800)
    
    # Run incremental refresh
    indexer.refresh()

    # 3. Assert deleted document is gone from Chroma and SQLite metadata
    docs_after = indexer.metadata_store.list_documents()
    assert len(docs_after) == 2
    assert "deleted.py" not in {doc.path for doc in docs_after}
    
    # Verify Chroma count is 2 (modified and unmodified)
    assert vector_store.collection.count() == 2

    # Verify search finds updated content
    search_results = vector_store.search("modified_updated_content", limit=1)
    assert len(search_results) == 1
    assert "modified_updated_content" in search_results[0].content
