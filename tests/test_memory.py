from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nakama_kun.ai.models.message import Message, ToolCall
from nakama_kun.memory import get_memory_repository
from nakama_kun.memory.noop import NoOpMemoryRepository
from nakama_kun.memory.sqlite import SQLiteMemoryRepository


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Fixture returning path to a temporary SQLite db file."""
    return tmp_path / "test_nakama.db"


def test_sqlite_memory_repository(temp_db_path: Path) -> None:
    """Test full SQLiteMemoryRepository operations and persistence."""
    repo = SQLiteMemoryRepository(str(temp_db_path))

    # 1. Test Conversations CRUD
    conv_id = repo.create_conversation("Test Conversation", "ask")
    assert conv_id is not None
    assert len(conv_id) > 0

    latest = repo.get_latest_conversation("ask")
    assert latest is not None
    assert latest["id"] == conv_id
    assert latest["title"] == "Test Conversation"
    assert latest["mode"] == "ask"

    convs = repo.get_conversations()
    assert len(convs) == 1
    assert convs[0]["id"] == conv_id

    # 2. Test Message CRUD with serialization
    tc = ToolCall(id="tc-123", function={"name": "test_tool", "arguments": {}})
    msg_user = Message(role="user", content="Hello!")
    msg_assistant = Message(
        role="assistant", content="Hi!", tool_calls=[tc], timestamp=datetime.now(UTC)
    )

    repo.add_message(conv_id, msg_user)
    repo.add_message(conv_id, msg_assistant)

    msgs = repo.get_messages(conv_id)
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[0].content == "Hello!"

    assert msgs[1].role == "assistant"
    assert msgs[1].content == "Hi!"
    assert msgs[1].tool_calls is not None
    assert len(msgs[1].tool_calls) == 1
    assert msgs[1].tool_calls[0].id == "tc-123"
    assert msgs[1].tool_calls[0].function["name"] == "test_tool"

    # 3. Test Project Context Summaries
    repo.save_project_summary("my-project", "Workspace structure summary details")
    summary = repo.get_project_summary("my-project")
    assert summary == "Workspace structure summary details"

    # Save same project summary to verify ON CONFLICT override
    repo.save_project_summary("my-project", "Updated workspace details")
    assert repo.get_project_summary("my-project") == "Updated workspace details"

    # 4. Test User Preferences CRUD
    repo.save_preference("model_preference", "gpt-4o")
    assert repo.get_preference("model_preference") == "gpt-4o"
    assert repo.get_preference("non_existent", "default") == "default"

    prefs = repo.get_all_preferences()
    assert prefs == {"model_preference": "gpt-4o"}

    repo.delete_preference("model_preference")
    assert repo.get_preference("model_preference") is None

    # 5. Test Agent Task Metadata
    repo.save_task_metadata("task-abc", "Analyze repository", "running")
    task = repo.get_task_metadata("task-abc")
    assert task is not None
    assert task["task_description"] == "Analyze repository"
    assert task["status"] == "running"

    repo.save_task_metadata("task-abc", "Analyze repository", "done")
    tasks = repo.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["status"] == "done"

    # 6. Test Clear operations
    repo.clear_conversation(conv_id)
    assert len(repo.get_messages(conv_id)) == 0

    repo.clear_all()
    assert len(repo.get_conversations()) == 0
    assert repo.get_project_summary("my-project") is None
    assert len(repo.list_tasks()) == 0


def test_noop_memory_repository() -> None:
    """Verify NoOpMemoryRepository behaves correctly and returns default fallback values."""
    repo = NoOpMemoryRepository()

    # Verify no exceptions and standard default returns
    assert repo.create_conversation("Title", "ask") == ""
    assert repo.get_conversations() == []
    assert repo.get_latest_conversation("plan") is None
    assert repo.get_messages("some-id") == []
    assert repo.get_project_summary("project") is None
    assert repo.get_preference("key", "val") == "val"
    assert repo.get_all_preferences() == {}
    assert repo.get_task_metadata("id") is None
    assert repo.list_tasks() == []


def test_memory_repository_factory(monkeypatch: pytest.MonkeyPatch, temp_db_path: Path) -> None:
    """Verify factory returns appropriate repository type based on config settings."""
    # Test SQLite configuration
    monkeypatch.setenv("MEMORY_ENABLED", "True")
    monkeypatch.setenv("MEMORY_DB_PATH", str(temp_db_path))

    repo = get_memory_repository()
    assert isinstance(repo, SQLiteMemoryRepository)
    assert repo.db_path == str(temp_db_path)

    # Test disabled configuration fallback
    monkeypatch.setenv("MEMORY_ENABLED", "False")
    repo_disabled = get_memory_repository()
    assert isinstance(repo_disabled, NoOpMemoryRepository)
