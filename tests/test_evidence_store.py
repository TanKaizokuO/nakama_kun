from unittest.mock import AsyncMock, MagicMock

import pytest

from nakama_kun.ai.models.plan import Plan
from nakama_kun.ai.models.response import AIResponse
from nakama_kun.orchestration.evidence import EvidenceStore, build_evidence_store
from nakama_kun.orchestration.nodes import make_reviewer_node, make_verifier_node
from nakama_kun.orchestration.state import AgentState
from nakama_kun.orchestration.verification import (
    CommandResult,
    ExistenceCheck,
    FileArtifact,
    VerificationReport,
)


def test_evidence_store_basic_build() -> None:
    mock_plan = Plan(
        goal_summary="Summary of goal",
        targets=["test.py"],
        assumptions=[],
        ordered_steps=["Step 1"],
        risks=[],
        validation_checklist=[],
    )

    mock_report = VerificationReport(
        files_created=[
            FileArtifact(path="result.py", exists=False, content_snippet="", size_bytes=0)
        ],
        files_modified=[],
        existence_checks=[
            ExistenceCheck(path="result.py", exists=False)
        ],
        command_results=[
            CommandResult(
                cmd="pytest",
                exit_code=1,
                stdout_snippet="Failed: assert 1 == 2",
                success=False,
                test_summary={
                    "passed": 2,
                    "failed": 1,
                    "errors": 0,
                    "skipped": 0,
                    "success": False,
                }
            )
        ],
        workspace_snapshot=[],
        summary="Verification failed."
    )

    state: AgentState = {
        "goal": "Write python file",
        "plan": mock_plan,
        "messages": [],
        "tool_results": [
            {
                "tool": "read_file",
                "arguments": {"path": "result.py"},
                "success": True,
                "content": "x = 42\ny = 24",
            },
            {
                "tool": "write_file",
                "arguments": {"path": "result.py", "content": "x = 42"},
                "success": True,
                "content": "Successfully wrote 6 characters.",
            },
            {
                "tool": "run_command",
                "arguments": {"cmd": "pytest"},
                "success": False,
                "content": "Exit code: 1\nFailed: assert 1 == 2",
            }
        ],
        "verification_report": mock_report,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }

    store = build_evidence_store(state, mock_report, "/tmp/workspace")
    assert isinstance(store, EvidenceStore)

    # 1. Tool outputs verified
    assert len(store.tool_outputs) == 3
    assert store.tool_outputs[0].tool == "read_file"
    assert store.tool_outputs[0].success is True
    assert store.tool_outputs[0].output == "x = 42\ny = 24"

    # 2. File validations verified
    assert len(store.file_validations) >= 3

    # Check that tool_read exists=True and content is preserved
    read_val = next(fv for fv in store.file_validations if fv.source == "tool_read")
    assert read_val.exists is True
    assert read_val.content == "x = 42\ny = 24"
    assert "result.py" in read_val.path

    # Check that disk check exists=False (matching mock_report)
    disk_val = next(fv for fv in store.file_validations if fv.source == "disk")
    assert disk_val.exists is False
    assert "result.py" in disk_val.path

    # 3. Command outputs verified
    assert len(store.command_outputs) == 1
    assert store.command_outputs[0].cmd == "pytest"
    assert store.command_outputs[0].exit_code == 1
    assert store.command_outputs[0].success is False

    # 4. Test outputs verified
    assert len(store.test_outputs) == 1
    assert store.test_outputs[0].cmd == "pytest"
    assert store.test_outputs[0].passed == 2
    assert store.test_outputs[0].failed == 1
    assert store.test_outputs[0].success is False


@pytest.mark.anyio
async def test_verifier_node_populates_evidence_store() -> None:
    verifier_node = make_verifier_node(workspace_root="/tmp/workspace")
    state: AgentState = {
        "goal": "Write python file",
        "plan": None,
        "messages": [],
        "tool_results": [
            {
                "tool": "read_file",
                "arguments": {"path": "a.txt"},
                "success": True,
                "content": "preserved content",
            }
        ],
        "verification_report": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "executing",
    }

    result = await verifier_node(state)
    assert "verification_report" in result
    assert "evidence_store" in result

    store = result["evidence_store"]
    assert isinstance(store, EvidenceStore)
    assert len(store.tool_outputs) == 1
    assert store.tool_outputs[0].tool == "read_file"
    assert store.tool_outputs[0].output == "preserved content"


@pytest.mark.anyio
async def test_reviewer_node_receives_evidence_store() -> None:
    mock_chat_service = MagicMock()
    mock_chat_service.provider = MagicMock()
    mock_chat_service.provider.generate = AsyncMock()

    mock_response = MagicMock(spec=AIResponse)
    mock_response.content = "[APPROVED] Evidence is satisfactory."
    mock_chat_service.provider.generate.return_value = mock_response

    reviewer_node = make_reviewer_node(mock_chat_service)

    # Construct state with evidence_store
    store = EvidenceStore()
    store.add_tool_output("read_file", {"path": "a.txt"}, True, "secret content")
    store.add_file_validation("/tmp/workspace/a.txt", True, "secret content", "tool_read")

    state: AgentState = {
        "goal": "Check secret",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "evidence_store": store,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }

    await reviewer_node(state)

    # Check generated prompt
    called_messages = mock_chat_service.provider.generate.call_args[0][0]
    user_msg = next(m for m in called_messages if m.role == "user")
    prompt = user_msg.content

    assert "=== EVIDENCE STORE (PRESERVED HISTORICAL EVIDENCE) ===" in prompt
    assert "secret content" in prompt
    assert "tool_read" in prompt
    assert "source: tool_read or tool_write" in prompt
