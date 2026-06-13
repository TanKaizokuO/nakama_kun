from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
import pytest

from nakama_kun.ai.models.message import Message
from nakama_kun.memory.models import SuccessfulTask, FailureRecord, UserPreference
from nakama_kun.memory.sqlite_store import SQLiteMemoryStore
from nakama_kun.memory.manager import MemoryManager
from nakama_kun.orchestration.nodes import make_reviewer_node
from nakama_kun.orchestration.state import AgentState, RetryMemory
from nakama_kun.orchestration.verification import VerificationReport, OutcomeSignal, FileArtifact


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Fixture returning path to a temporary SQLite db file."""
    return tmp_path / "test_memory.db"


@pytest.fixture
def store(temp_db_path: Path) -> SQLiteMemoryStore:
    return SQLiteMemoryStore(str(temp_db_path))


@pytest.fixture
def manager(store: SQLiteMemoryStore, tmp_path: Path) -> MemoryManager:
    return MemoryManager(store, workspace_root=tmp_path)


def test_sqlite_memory_store_basics(store: SQLiteMemoryStore) -> None:
    # 1. Save and retrieve successful task
    now = datetime.now(UTC)
    task = SuccessfulTask(
        goal="Build a FastAPI app",
        plan_summary="1. Setup 2. Code",
        files_changed=["main.py", "requirements.txt"],
        tools_used=["write_file", "run_command"],
        outcome="API is running on port 8000.",
        timestamp=now,
    )
    store.save_success(task)
    successes = store.get_successes()
    assert len(successes) == 1
    assert successes[0].goal == "Build a FastAPI app"
    assert successes[0].files_changed == ["main.py", "requirements.txt"]
    assert successes[0].tools_used == ["write_file", "run_command"]
    assert successes[0].outcome == "API is running on port 8000."
    assert abs((successes[0].timestamp - now).total_seconds()) < 1.0

    # 2. Save and retrieve failure record
    failure = FailureRecord(
        goal="Run tests",
        attempted_actions=["pytest tests/"],
        failure_type="TEST_FAILURE",
        failure_message="ModuleNotFoundError: No module named 'fastapi'",
        resolution="Install fastapi using pip",
        timestamp=now,
    )
    store.save_failure(failure)
    failures = store.get_failures()
    assert len(failures) == 1
    assert failures[0].goal == "Run tests"
    assert failures[0].attempted_actions == ["pytest tests/"]
    assert failures[0].failure_type == "TEST_FAILURE"
    assert failures[0].failure_message == "ModuleNotFoundError: No module named 'fastapi'"
    assert failures[0].resolution == "Install fastapi using pip"
    assert abs((failures[0].timestamp - now).total_seconds()) < 1.0

    # 3. Save and retrieve user preference
    pref = UserPreference(
        key="testing",
        value="pytest",
        confidence=0.8,
        source="project_dependencies",
        updated_at=now,
    )
    store.save_preference(pref)
    prefs = store.get_preferences()
    assert len(prefs) == 1
    assert prefs[0].key == "testing"
    assert prefs[0].value == "pytest"
    assert prefs[0].confidence == 0.8
    assert prefs[0].source == "project_dependencies"
    assert abs((prefs[0].updated_at - now).total_seconds()) < 1.0


def test_memory_manager_deduplication(manager: MemoryManager, store: SQLiteMemoryStore) -> None:
    # Test Success Deduplication
    manager.save_successful_task(
        goal="Test Goal",
        plan_summary="Plan Summary",
        files_changed=["file1.py"],
        tools_used=["tool1"],
        outcome="Finished",
    )
    # Save exact duplicate
    manager.save_successful_task(
        goal="Test Goal",
        plan_summary="Plan Summary",
        files_changed=["file1.py"],
        tools_used=["tool1"],
        outcome="Finished",
    )
    assert len(store.get_successes()) == 1

    # Test Failure Deduplication
    manager.save_failure_record(
        goal="Fail Goal",
        attempted_actions=["action1"],
        failure_type="QA_REJECTION",
        failure_message="Missing file",
        resolution="Re-run",
    )
    # Save exact duplicate failure_message + goal
    manager.save_failure_record(
        goal="Fail Goal",
        attempted_actions=["action1"],
        failure_type="QA_REJECTION",
        failure_message="Missing file",
        resolution="Re-run",
    )
    assert len(store.get_failures()) == 1


def test_preference_learning_and_merging(manager: MemoryManager, store: SQLiteMemoryStore, tmp_path: Path) -> None:
    # 1. Setup mock workspace snapshot dependencies
    workspace_dir = tmp_path / ".workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = workspace_dir / "workspace_snapshot.json"
    snapshot_data = {
        "dependencies": ["ruff", "pytest", "fastapi"]
    }
    snapshot_path.write_text(json.dumps(snapshot_data), encoding="utf-8")

    # 2. Learn from goal and dependencies
    goal = "I want strict typing and pydantic in this project."
    manager.learn_preferences(goal)

    prefs = {p.key: p for p in store.get_preferences()}
    assert "typing" in prefs
    assert prefs["typing"].value == "strict"
    assert prefs["typing"].confidence == 0.5
    assert prefs["typing"].source == "user_goal"

    assert "linter" in prefs
    assert prefs["linter"].value == "ruff"
    assert prefs["linter"].confidence == 0.5
    assert prefs["linter"].source == "project_dependencies"

    assert "validation" in prefs
    assert prefs["validation"].value == "pydantic"
    assert prefs["validation"].confidence == 0.5
    assert prefs["validation"].source == "user_goal"

    # 3. Test confidence increment on match
    manager.learn_preferences(goal)
    prefs_updated = {p.key: p for p in store.get_preferences()}
    assert prefs_updated["typing"].confidence == pytest.approx(0.6)
    assert prefs_updated["linter"].confidence == pytest.approx(0.6)

    # 4. Test conflict decrement and overwrite
    # Manually seed a conflicting linter preference "flake8" with confidence 0.3
    conflict_pref = UserPreference(
        key="linter",
        value="flake8",
        confidence=0.3,
        source="user_goal",
        updated_at=datetime.now(UTC),
    )
    store.save_preference(conflict_pref)

    # Trigger learning which tries to set "linter" -> "ruff" (from dependencies/goal)
    manager.learn_preferences("No special linter in this goal")
    prefs_conflict = {p.key: p for p in store.get_preferences()}
    # Confidence of "flake8" should decrease: 0.3 - 0.2 = 0.1
    assert prefs_conflict["linter"].value == "flake8"
    assert prefs_conflict["linter"].confidence == pytest.approx(0.1)

    # Trigger conflict again: confidence drops below 0 (0.1 - 0.2 = -0.1 < 0.0) -> Overwrite with "ruff"
    manager.learn_preferences("No special linter in this goal")
    prefs_overwritten = {p.key: p for p in store.get_preferences()}
    assert prefs_overwritten["linter"].value == "ruff"
    assert prefs_overwritten["linter"].confidence == 0.5


@pytest.mark.anyio
async def test_reviewer_node_success_logging(monkeypatch: pytest.MonkeyPatch, temp_db_path: Path, tmp_path: Path) -> None:
    # Configure memory environment variables
    monkeypatch.setenv("MEMORY_ENABLED", "True")
    monkeypatch.setenv("MEMORY_DB_PATH", str(temp_db_path))

    # Mock chat_service
    from unittest.mock import MagicMock
    mock_chat = MagicMock()
    # We want it to be classified as legacy logic mock to bypass ReviewerAgent for simple deterministic response testing
    mock_chat.__class__.__name__ = "Mock"

    # Create reviewer node
    node = make_reviewer_node(mock_chat, workspace_root=str(tmp_path))

    # Setup state
    state: AgentState = {
        "goal": "Ensure ruff and pytest are set up.",
        "plan": MagicMock(goal_summary="1. Setup ruff 2. Setup pytest"),
        "required_artifacts": [],
        "created_artifacts": [],
        "missing_artifacts": [],
        "research_budget_remaining": 3,
        "delivery_mode": False,
        "retry_memory": {
            "completed_actions": ["Ruff setup ran successfully"],
            "failed_actions": [],
            "failed_validations": [],
            "reviewer_feedback": [],
            "failed_attempt_signatures": [],
        },
        "messages": [],
        "tool_results": [
            {"tool": "write_file", "arguments": {"path": "pyproject.toml"}, "success": True, "content": "Ruff configuration"},
        ],
        "verification_report": VerificationReport(
            files_created=[FileArtifact("pyproject.toml", True, "ruff", 10)],
            files_modified=[],
            existence_checks=[],
            command_results=[],
            workspace_snapshot=["pyproject.toml"],
            summary="1 file created",
        ),
        "evidence_store": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
        "coder_proposals": [],
        "agent_history": [],
        "reviewer_route": None,
        "task_type": "MODIFICATION",
        "goal_satisfied": False,
        "early_stop_telemetry": None,
    }

    # Mock chat service response content to be approved
    mock_response = MagicMock()
    mock_response.content = "[APPROVED]\nThe implementation of ruff is verified."
    from unittest.mock import AsyncMock
    mock_chat.provider.generate = AsyncMock(return_value=mock_response)

    # Run reviewer node
    res = await node(state)

    # Assert reviewer node return status
    assert res["status"] == "done"
    assert res["reviewer_feedback"] is None

    # Check store database to verify SuccessfulTask is written
    store = SQLiteMemoryStore(str(temp_db_path))
    successes = store.get_successes()
    assert len(successes) == 1
    assert successes[0].goal == "Ensure ruff and pytest are set up."
    assert "pyproject.toml" in successes[0].files_changed
    assert "write_file" in successes[0].tools_used
    assert "Ruff setup ran successfully" in state["retry_memory"]["completed_actions"]


@pytest.mark.anyio
async def test_reviewer_node_failure_logging(monkeypatch: pytest.MonkeyPatch, temp_db_path: Path, tmp_path: Path) -> None:
    # Configure memory environment
    monkeypatch.setenv("MEMORY_ENABLED", "True")
    monkeypatch.setenv("MEMORY_DB_PATH", str(temp_db_path))

    # Mock chat_service as legacy mock
    from unittest.mock import MagicMock
    mock_chat = MagicMock()
    mock_chat.__class__.__name__ = "Mock"

    # Create reviewer node
    node = make_reviewer_node(mock_chat, workspace_root=str(tmp_path))

    # Setup state with a failure condition
    state: AgentState = {
        "goal": "Write main.py",
        "plan": MagicMock(goal_summary="Create main.py"),
        "required_artifacts": ["main.py"],
        "created_artifacts": [],
        "missing_artifacts": ["main.py"],  # Trigger missing artifact gate
        "research_budget_remaining": 3,
        "delivery_mode": False,
        "retry_memory": {
            "completed_actions": [],
            "failed_actions": [],
            "failed_validations": [],
            "reviewer_feedback": [],
            "failed_attempt_signatures": [],
        },
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "evidence_store": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
        "coder_proposals": [],
        "agent_history": [],
        "reviewer_route": None,
        "task_type": "MODIFICATION",
        "goal_satisfied": False,
        "early_stop_telemetry": None,
    }

    # Run reviewer node
    res = await node(state)

    assert res["status"] == "planning"
    assert "Missing Required Artifacts" in res["reviewer_feedback"]

    # Verify FailureRecord is written to store
    store = SQLiteMemoryStore(str(temp_db_path))
    failures = store.get_failures()
    assert len(failures) == 1
    assert failures[0].goal == "Write main.py"
    assert failures[0].failure_type == "MISSING_ARTIFACTS"
    assert "Missing Required Artifacts" in failures[0].failure_message
    assert failures[0].resolution == "Route to planner"
