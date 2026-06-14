from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nakama_kun.agents.planner import PlannerAgent
from nakama_kun.ai.models.response import AIResponse
from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.rag.retriever import (
    Retriever,
    RetrievalResult,
    RetrievalStrategy,
    RepositoryKnowledgeService,
    format_planner_knowledge_context,
)
from nakama_kun.rag.vector_store import DocumentChunk, VectorStore


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def mock_chat_service() -> MagicMock:
    service = MagicMock(spec=ChatService)
    service.provider = MagicMock()
    service.provider.generate = AsyncMock()
    service.chat_with_tools = AsyncMock()
    return service


@pytest.fixture
def dummy_workspace_metadata(temp_workspace: Path) -> Path:
    workspace_dir = temp_workspace / ".workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create workspace_snapshot.json
    snapshot = {
        "files": [
            "src/verification.py",
            "tests/test_verification.py",
            "docs/design/EVIDENCE_PIPELINE.md",
            "src/retry_memory.py",
            "src/reviewer.py",
        ],
        "folders": ["src", "tests", "docs"],
        "tests": {
            "directories": ["tests"],
            "files": ["tests/test_verification.py"],
        },
        "languages": {"python": 4, "markdown": 1},
    }
    with open(workspace_dir / "workspace_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(snapshot, f)

    # 2. Create symbol_index.json
    symbol_index = {
        "metadata": {"files_mtime": {}},
        "symbols": [
            {
                "name": "verify_artifacts",
                "type": "function",
                "file": "src/verification.py",
                "line": 10,
            },
            {
                "name": "RetryMemory",
                "type": "class",
                "file": "src/retry_memory.py",
                "line": 5,
            },
        ],
    }
    with open(workspace_dir / "symbol_index.json", "w", encoding="utf-8") as f:
        json.dump(symbol_index, f)

    # 3. Create dependency_graph.json
    dependency_graph = {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [
            {"id": "src/verification.py", "type": "file"},
            {"id": "tests/test_verification.py", "type": "file"},
        ],
        "links": [
            {"source": 1, "target": 0}  # tests/test_verification.py -> src/verification.py
        ],
    }
    with open(workspace_dir / "dependency_graph.json", "w", encoding="utf-8") as f:
        json.dump(dependency_graph, f)

    return temp_workspace


@pytest.mark.anyio
async def test_planner_agent_receives_retrieval_context(
    mock_chat_service: MagicMock,
) -> None:
    # Set up mock retriever
    mock_retriever = MagicMock()
    mock_retriever.retrieve_planner_context.return_value = (
        "### Relevant Repository Knowledge\n\n"
        "Source:\nverification.py\n\n"
        "Relevance Score: 0.95\n\n"
        "Summarized Content:\nThis is verification.py content"
    )

    plan_text = json.dumps({
        "goal_summary": "Test Planning RAG",
        "assumptions": [],
        "ordered_steps": ["Step 1"],
        "required_artifacts": [],
        "risks": [],
        "validation_checklist": [],
        "targets": [],
    })
    mock_chat_service.provider.generate.return_value = AIResponse(
        content=plan_text, finish_reason="stop", model="mock-model"
    )

    state: dict[str, Any] = {
        "goal": "How does verification work?",
        "reviewer_feedback": None,
        "retry_count": 0,
        "agent_history": [],
    }

    # Patch get_retriever to return our mock retriever
    with patch("nakama_kun.agents.planner.get_retriever", return_value=mock_retriever):
        agent = PlannerAgent(mock_chat_service)
        res = await agent.run(state)

    # Verify LLM call system prompt contains the Relevant Repository Knowledge block
    assert mock_chat_service.provider.generate.called
    call_args = mock_chat_service.provider.generate.call_args[0][0]
    system_prompt = call_args[0].content

    assert "### Relevant Repository Knowledge" in system_prompt
    assert "Source:\nverification.py" in system_prompt
    assert "Relevance Score: 0.95" in system_prompt
    assert "Summarized Content:" in system_prompt


def test_repository_routing_and_workspace_metadata(dummy_workspace_metadata: Path) -> None:
    # 1. Test "How does verification work?" query
    strategy_verif = RetrievalStrategy("How does verification work?", workspace_root=dummy_workspace_metadata)
    assert strategy_verif.limit == 10
    assert "test" in strategy_verif.prioritized_types
    # src/verification.py should be in prioritized paths since name/stem matches
    assert "src/verification.py" in strategy_verif.prioritized_paths
    # tests/test_verification.py should be in prioritized paths due to dependency links or name match
    assert "tests/test_verification.py" in strategy_verif.prioritized_paths

    # 2. Test "How does retry memory work?" query
    strategy_retry = RetrievalStrategy("How does retry memory work?", workspace_root=dummy_workspace_metadata)
    assert strategy_retry.limit == 10
    assert "retry_memory" in strategy_retry.prioritized_types
    # src/retry_memory.py contains definition for RetryMemory class in symbol_index
    assert "src/retry_memory.py" in strategy_retry.prioritized_paths


def test_token_budget_limits() -> None:
    # Create large chunks
    results = [
        RetrievalResult(
            content="A" * 1000,
            source_path="src/a.py",
            source_type="python_source",
            score=0.95,
            metadata={},
        ),
        RetrievalResult(
            content="B" * 1000,
            source_path="src/b.py",
            source_type="python_source",
            score=0.85,
            metadata={},
        ),
    ]

    # Format context
    context = format_planner_knowledge_context(results)
    assert "Source:\na.py" in context
    assert "Source:\nb.py" in context
    assert "Relevance Score: 0.95" in context
    assert "Relevance Score: 0.85" in context


def test_retrieval_quality_under_large_repositories(dummy_workspace_metadata: Path) -> None:
    mock_store = MagicMock(spec=VectorStore)
    mock_store.db_path = dummy_workspace_metadata / ".rag" / "chroma"

    # Return a mix of matching files and noisy files
    candidates = [
        DocumentChunk(
            id="noise1",
            source_type="python_source",
            source_path="src/unrelated.py",
            content="noise content unrelated to query",
            metadata={},
        ),
        DocumentChunk(
            id="verif1",
            source_type="python_source",
            source_path="src/verification.py",
            content="def verify_artifacts():\n    pass",
            metadata={"symbol_names": "verify_artifacts"},
        ),
    ]
    mock_store.search.return_value = candidates

    retriever = Retriever(mock_store)

    # Search for verification topics. The verification.py candidate should get boosted.
    results = retriever.retrieve("How does verification work?", limit=5)
    
    assert len(results) == 2
    # verification.py should be first because of boosts (+0.25 path boost, +0.15 type boost, +0.20 symbol boost, +0.10 code preferred)
    assert results[0].source_path == "src/verification.py"
    assert results[0].score > results[1].score


def test_repository_knowledge_service_apis(dummy_workspace_metadata: Path) -> None:
    mock_retriever = MagicMock(spec=Retriever)
    
    service = RepositoryKnowledgeService(retriever=mock_retriever, workspace_root=str(dummy_workspace_metadata))
    
    # 1. ask_repository
    service.ask_repository("query")
    mock_retriever.retrieve.assert_called_with("query", limit=10)

    # 2. find_implementation
    service.find_implementation("topic")
    mock_retriever.retrieve_with_filters.assert_called_with("topic", {"source_type": "python_source"}, limit=5)

    # 3. find_tests_for_component
    service.find_tests_for_component("comp")
    mock_retriever.retrieve_with_filters.assert_called_with("comp", {"source_type": "test"}, limit=5)

    # 4. find_related_files
    # src/verification.py has a predecessor in dependency_graph: tests/test_verification.py
    related = service.find_related_files("src/verification.py")
    assert "tests/test_verification.py" in related
