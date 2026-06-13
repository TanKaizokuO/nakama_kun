from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.ai.services.planner_service import PlannerService
from nakama_kun.modes.ask_mode import AskMode
from nakama_kun.rag import get_vector_store
from nakama_kun.rag.embeddings import LocalEmbeddingProvider
from nakama_kun.rag.indexer import Indexer
from nakama_kun.rag.vector_store import ChromaVectorStore, DocumentChunk


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def mock_embedding_provider() -> LocalEmbeddingProvider:
    # Forces the fallback pure-Python hashing path to run predictably
    provider = LocalEmbeddingProvider(dimension=384)
    provider._use_fallback = True
    return provider


@pytest.fixture
def clean_rag_settings(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Point settings to temp workspace paths
    monkeypatch.setenv("RAG_ENABLED", "True")
    monkeypatch.setenv("RAG_DB_PATH", str(temp_workspace / ".nakama_rag"))
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("RAG_CHUNK_SIZE_LINES", "10")
    monkeypatch.setenv("RAG_CHUNK_OVERLAP_LINES", "2")


@pytest.fixture(autouse=True)
def mock_fetch_task_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    from nakama_kun.rag.indexer import Indexer
    monkeypatch.setattr(Indexer, "fetch_task_chunks", lambda self: [])


def test_local_hashing_fallback_properties(mock_embedding_provider: LocalEmbeddingProvider) -> None:
    # 1. Deterministic
    vec1 = mock_embedding_provider.embed_query("hello world")
    vec2 = mock_embedding_provider.embed_query("hello world")
    assert vec1 == vec2
    assert len(vec1) == 384

    # 2. Normalized (L2 norm should be close to 1.0)
    norm = sum(x * x for x in vec1)
    assert abs(norm - 1.0) < 1e-5

    # 3. Differentiates content
    vec3 = mock_embedding_provider.embed_query("different code snippet")
    assert vec1 != vec3


def test_chunking_and_filtering(temp_workspace: Path, mock_embedding_provider: LocalEmbeddingProvider) -> None:
    vector_store = ChromaVectorStore(
        db_path=str(temp_workspace / ".chromadb"),
        embedding_provider=mock_embedding_provider,
    )
    indexer = Indexer(
        workspace_root=str(temp_workspace),
        vector_store=vector_store,
        chunk_size_lines=5,
        chunk_overlap_lines=1,
    )

    # Create Python text file
    py_file = temp_workspace / "utils.py"
    py_file.write_text("\n".join([f"line_{i}" for i in range(1, 11)]))

    # Create Binary file
    bin_file = temp_workspace / "image.png"
    bin_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")

    # Create Secret file
    secret_file = temp_workspace / ".env"
    secret_file.write_text("API_KEY=supersecretkeyhere")

    # 1. Chunk Python file
    chunks = indexer.chunk_file("utils.py")
    # Expected line boundaries: 1-5, 5-9, 9-10
    assert len(chunks) == 3
    assert chunks[0].metadata["line_start"] == 1
    assert chunks[0].metadata["line_end"] == 5
    assert chunks[1].metadata["line_start"] == 5
    assert chunks[1].metadata["line_end"] == 9
    assert chunks[2].metadata["line_start"] == 9
    assert chunks[2].metadata["line_end"] == 10

    # 2. Binary file should be ignored
    bin_chunks = indexer.chunk_file("image.png")
    assert len(bin_chunks) == 0

    # 3. Secret file should be ignored
    secret_chunks = indexer.chunk_file(".env")
    assert len(secret_chunks) == 0


def test_vector_store_indexing_and_search(temp_workspace: Path, mock_embedding_provider: LocalEmbeddingProvider) -> None:
    vector_store = ChromaVectorStore(
        db_path=str(temp_workspace / ".chromadb"),
        embedding_provider=mock_embedding_provider,
    )

    chunks = [
        DocumentChunk(
            id="file1.py:1-5",
            content="def calculate_total(items):\n    return sum(items)",
            metadata={"path": "file1.py", "language": "Python", "type": "file"},
        ),
        DocumentChunk(
            id="file2.py:1-5",
            content="class DatabaseConnector:\n    def connect(self): pass",
            metadata={"path": "file2.py", "language": "Python", "type": "file"},
        ),
    ]

    vector_store.add_chunks(chunks)

    # Verify search returns the most relevant chunk
    results = vector_store.search("calculate sum of items", limit=1)
    assert len(results) == 1
    assert results[0].id == "file1.py:1-5"
    assert "calculate_total" in results[0].content


def test_indexer_incremental_refresh(temp_workspace: Path, mock_embedding_provider: LocalEmbeddingProvider) -> None:
    vector_store = ChromaVectorStore(
        db_path=str(temp_workspace / ".chromadb"),
        embedding_provider=mock_embedding_provider,
    )
    indexer = Indexer(
        workspace_root=str(temp_workspace),
        vector_store=vector_store,
        chunk_size_lines=10,
        chunk_overlap_lines=0,
    )

    # Setup files
    (temp_workspace / "unmodified.py").write_text("x = 10")
    (temp_workspace / "modified.py").write_text("y = 20")
    (temp_workspace / "deleted.py").write_text("z = 30")

    # Initial build
    indexer.build()
    assert vector_store.collection.count() == 3

    # Delete 'deleted.py'
    os.remove(temp_workspace / "deleted.py")

    # Modify 'modified.py'
    modified_path = temp_workspace / "modified.py"
    modified_path.write_text("y = 999\nupdated_code = True")
    # Touch file to update mtime explicitly
    os.utime(modified_path, (modified_path.stat().st_atime, modified_path.stat().st_mtime + 5))

    # Incremental refresh
    indexer.refresh()

    # Verify deleted file chunks are removed, modified is updated, unmodified remains
    assert vector_store.collection.count() == 2

    # Query modified file content
    res = vector_store.search("updated_code", limit=1)
    assert len(res) == 1
    assert "y = 999" in res[0].content


def test_ask_and_plan_prompt_integration(
    temp_workspace: Path,
    clean_rag_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. Build a mock index first
    store = get_vector_store(str(temp_workspace))
    assert store is not None
    store.clear()

    test_chunks = [
        DocumentChunk(
            id="app.py:1-2",
            content="def wake_up():\n    return 'wakeup'",
            metadata={"path": "app.py", "language": "Python", "type": "file"},
        )
    ]
    store.add_chunks(test_chunks)

    # Mock get_retriever to return our mock store's retriever
    from nakama_kun.rag.retriever import Retriever
    retriever = Retriever(vector_store=store)
    monkeypatch.setattr("nakama_kun.rag.get_retriever", lambda *args, **kwargs: retriever)

    # 2. Test AskMode prompt generation
    mock_provider = MagicMock()
    mock_provider.settings.openrouter_model = "test-model"
    chat_service = ChatService(mock_provider)

    # Instantiate AskMode and trigger loop mock message to set system prompt
    ask_mode = AskMode(chat_service)
    assert ask_mode.name == "Ask Mode"
    # Simulate turn
    # We call the internal logic of AskMode turn
    from nakama_kun.ai.prompts.system_prompt import ASK_SYSTEM_PROMPT
    from nakama_kun.workspace.context import WorkspaceContextBuilder
    workspace_context = WorkspaceContextBuilder(str(temp_workspace)).build_summary()
    system_prompt = f"{ASK_SYSTEM_PROMPT}\n\n{workspace_context}"
    assert len(system_prompt) > 0

    # Query retriever
    rag_context = retriever.retrieve_formatted_context("wake_up")
    assert "def wake_up():" in rag_context
    assert "app.py" in rag_context

    # 3. Test PlannerService context retrieval
    planner_service = PlannerService(chat_service)
    # We call plan, which automatically builds prompt using RAG
    # Mock LLM response
    from unittest.mock import AsyncMock
    mock_response = MagicMock()
    mock_response.content = "goal_summary: Done\nordered_steps:\n1. Done"
    chat_service.provider.generate = AsyncMock(return_value=mock_response)

    # Run planning
    import asyncio
    async def run_plan():
        _, raw = await planner_service.plan("wake_up")
        return raw

    asyncio.run(run_plan())

    # Verify RAG context was injected into the call messages
    call_args = chat_service.provider.generate.call_args[0][0]
    system_msg = next(m for m in call_args if m.role == "system")
    assert "def wake_up():" in system_msg.content
    assert "app.py" in system_msg.content
