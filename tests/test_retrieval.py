from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nakama_kun.rag.vector_store import DocumentChunk, VectorStore
from nakama_kun.rag.retriever import Retriever, RetrievalResult, BGEReranker, ContextAssembler


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def mock_vector_store() -> MagicMock:
    store = MagicMock(spec=VectorStore)
    store.db_path = "/workspace/.rag/chroma"
    return store


@pytest.fixture
def test_chunks() -> list[DocumentChunk]:
    return [
        DocumentChunk(
            id="src/verification.py:1-10",
            source_type="python_source",
            source_path="src/verification.py",
            content="def verify_artifacts(state):\n    logger.info('Verifying artifacts')\n    return True",
            metadata={"path": "src/verification.py", "language": "Python", "line_start": 1, "line_end": 10, "symbol_names": "verify_artifacts", "document_type": "python_source"},
        ),
        DocumentChunk(
            id="src/verification.py:8-15",
            source_type="python_source",
            source_path="src/verification.py",
            content="    logger.info('Verifying artifacts')\n    return True\n# End of verifier",
            metadata={"path": "src/verification.py", "language": "Python", "line_start": 8, "line_end": 15, "symbol_names": "verify_artifacts", "document_type": "python_source"},
        ),
        DocumentChunk(
            id="docs/design/EVIDENCE_PIPELINE.md:1-5",
            source_type="documentation",
            source_path="docs/design/EVIDENCE_PIPELINE.md",
            content="# Evidence Pipeline Analysis\nDetails of evidence store verification outcomes.",
            metadata={"path": "docs/design/EVIDENCE_PIPELINE.md", "language": "Markdown", "line_start": 1, "line_end": 5, "section_title": "Evidence Pipeline Analysis", "document_type": "documentation"},
        ),
        DocumentChunk(
            id="tests/test_verification.py:1-5",
            source_type="test",
            source_path="tests/test_verification.py",
            content="def test_verifier_node():\n    assert True",
            metadata={"path": "tests/test_verification.py", "language": "Python", "line_start": 1, "line_end": 5, "symbol_names": "test_verifier_node", "document_type": "test"},
        ),
    ]


def test_semantic_search_retrieval(mock_vector_store: MagicMock, test_chunks: list[DocumentChunk]) -> None:
    # 1. Setup mock search return
    mock_vector_store.search.return_value = test_chunks
    
    retriever = Retriever(mock_vector_store)
    results = retriever.retrieve("How does verification work?", limit=4)
    
    # Verify we got results
    assert len(results) == 4
    # Ensure they are instances of RetrievalResult
    assert isinstance(results[0], RetrievalResult)
    # Check that they contain correct sources
    paths = {r.source_path for r in results}
    assert "src/verification.py" in paths
    assert "docs/design/EVIDENCE_PIPELINE.md" in paths
    assert "tests/test_verification.py" in paths


def test_bge_reranker_fallback(test_chunks: list[DocumentChunk]) -> None:
    # Initialize reranker with fallback forced
    reranker = BGEReranker(use_fallback=True)
    
    # Query with strong overlap to verification.py content
    query = "verify_artifacts verification tests"
    reranked = reranker.rerank(query, test_chunks)
    
    # Should return a list of tuples (chunk, score)
    assert len(reranked) == len(test_chunks)
    
    # Map by chunk ID to avoid overwriting scores from same file path
    scores_by_id = {chunk.id: score for chunk, score in reranked}
    assert scores_by_id["src/verification.py:1-10"] > scores_by_id["docs/design/EVIDENCE_PIPELINE.md:1-5"]


def test_metadata_filtering(mock_vector_store: MagicMock, test_chunks: list[DocumentChunk]) -> None:
    mock_vector_store.search.return_value = test_chunks
    retriever = Retriever(mock_vector_store)
    
    # Retrieve only "test" source_type
    results = retriever.retrieve_by_type("verifier", "test")
    assert len(results) == 1
    assert results[0].source_path == "tests/test_verification.py"
    
    # Filter by symbol name
    symbol_filtered = retriever.retrieve_with_filters("verifier", {"symbol_name": "verify_artifacts"})
    assert len(symbol_filtered) == 2
    assert symbol_filtered[0].source_path == "src/verification.py"


def test_context_assembler_dedup_and_merge(temp_workspace: Path) -> None:
    # Create physical file in temp workspace to allow line range reading
    file_path = temp_workspace / "src" / "verification.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_lines = [f"line_{i}" for i in range(1, 21)]
    file_path.write_text("\n".join(file_lines))

    # Create duplicate retrieval results and adjacent ones
    results = [
        # Chunk 1 (lines 1 to 5)
        RetrievalResult(
            content="line_1\nline_2\nline_3\nline_4\nline_5",
            source_path="src/verification.py",
            source_type="python_source",
            score=0.9,
            metadata={"line_start": 1, "line_end": 5, "language": "Python"}
        ),
        # Chunk 2 (duplicate content of Chunk 1)
        RetrievalResult(
            content="line_1\nline_2\nline_3\nline_4\nline_5",
            source_path="src/verification.py",
            source_type="python_source",
            score=0.85,
            metadata={"line_start": 1, "line_end": 5, "language": "Python"}
        ),
        # Chunk 3 (contiguous lines 5 to 10)
        RetrievalResult(
            content="line_5\nline_6\nline_7\nline_8\nline_9\nline_10",
            source_path="src/verification.py",
            source_type="python_source",
            score=0.8,
            metadata={"line_start": 5, "line_end": 10, "language": "Python"}
        )
    ]

    assembler = ContextAssembler(token_budget=1000, workspace_root=str(temp_workspace))
    context = assembler.assemble(results)

    # 1. Assert deduplication (only one unique entry for line_1...5 is processed)
    # 2. Assert adjacent line merging (lines 1-5 and 5-10 are contiguous/overlapping and get merged to 1-10)
    assert "lines 1-10" in context
    assert "line_1\nline_2" in context
    assert "line_9\nline_10" in context
    
    # 3. Attributed format check
    assert "File: `src/verification.py`" in context


def test_context_assembler_token_budget() -> None:
    # Setup results that exceed budget
    results = [
        RetrievalResult(
            content="A" * 1200,
            source_path="file1.txt",
            source_type="documentation",
            score=0.9,
            metadata={"line_start": 1, "line_end": 10, "language": "Text"}
        ),
        RetrievalResult(
            content="B" * 1200,
            source_path="file2.txt",
            source_type="documentation",
            score=0.8,
            metadata={"line_start": 1, "line_end": 10, "language": "Text"}
        )
    ]

    # Configure a tiny budget of 400 tokens (~1600 characters max, including header)
    # This should fit the first chunk, but drop the second one
    assembler = ContextAssembler(token_budget=400)
    context = assembler.assemble(results)
    
    assert "file1.txt" in context
    assert "file2.txt" not in context
