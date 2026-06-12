import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from nakama_kun.orchestration.nodes import make_final_response_node
from nakama_kun.orchestration.state import AgentState
from nakama_kun.orchestration.verification import VerificationReport, FileArtifact, CommandResult
from nakama_kun.ai.models.response import AIResponse
from nakama_kun.ai.models.plan import Plan


@pytest.mark.anyio
async def test_final_response_grounding_with_report() -> None:
    mock_chat_service = MagicMock()
    mock_chat_service.provider = MagicMock()
    mock_chat_service.provider.generate = AsyncMock()

    mock_llm_response = MagicMock(spec=AIResponse)
    mock_llm_response.content = "Summary created."
    mock_chat_service.provider.generate.return_value = mock_llm_response

    final_response_node = make_final_response_node(mock_chat_service)

    # 1. Verification report containing files and test counts
    mock_report = VerificationReport(
        files_created=[
            FileArtifact(path="/workspace/build.py", exists=True, content_snippet="x=1", size_bytes=3),
            FileArtifact(path="/workspace/missing.py", exists=False, content_snippet="", size_bytes=0)
        ],
        files_modified=[
            FileArtifact(path="/workspace/main.py", exists=True, content_snippet="x=2", size_bytes=3)
        ],
        existence_checks=[],
        command_results=[
            CommandResult(
                cmd="pytest",
                exit_code=0,
                stdout_snippet="10 passed",
                success=True,
                test_summary={
                    "passed": 10,
                    "failed": 0,
                    "errors": 0,
                    "skipped": 1,
                    "success": True,
                }
            )
        ],
        workspace_snapshot=["build.py", "main.py"],
        summary="Verified."
    )

    state: AgentState = {
        "goal": "Write code and test",
        "plan": Plan(
            goal_summary="Test plan",
            targets=["main.py"],
            assumptions=[],
            ordered_steps=["Step 1"],
            risks=[],
            validation_checklist=[],
        ),
        "messages": [],
        "tool_results": [{"tool": "write_file", "success": True, "content": "Ok"}],
        "verification_report": mock_report,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }

    result = await final_response_node(state)
    assert result["final_response"] == "Summary created."
    assert result["status"] == "done"

    # Verify summary prompt contains exact grounding metrics
    called_messages = mock_chat_service.provider.generate.call_args[0][0]
    user_msg = next(m for m in called_messages if m.role == "user")
    prompt = user_msg.content

    assert "### STRUCTURED METRICS" in prompt
    assert "/workspace/build.py" in prompt
    assert "/workspace/main.py" in prompt
    assert "/workspace/missing.py" not in prompt  # Since exists=False
    assert "Passed: 10" in prompt
    assert "Failed: 0" in prompt
    assert "Skipped: 1" in prompt
    assert "Workspace Snapshot (2 files):" in prompt
    assert "You MUST only cite the files created/modified and test counts" in prompt


@pytest.mark.anyio
async def test_final_response_grounding_fallback_no_report() -> None:
    mock_chat_service = MagicMock()
    mock_chat_service.provider = MagicMock()
    mock_chat_service.provider.generate = AsyncMock()

    mock_llm_response = MagicMock(spec=AIResponse)
    mock_llm_response.content = "Summary created."
    mock_chat_service.provider.generate.return_value = mock_llm_response

    final_response_node = make_final_response_node(mock_chat_service)

    # 2. No verification report — tool results fallback
    state: AgentState = {
        "goal": "Write code and test",
        "plan": Plan(
            goal_summary="Test plan",
            targets=["main.py"],
            assumptions=[],
            ordered_steps=["Step 1"],
            risks=[],
            validation_checklist=[],
        ),
        "messages": [],
        "tool_results": [
            {
                "tool": "write_file",
                "success": True,
                "arguments": {"path": "result.py", "content": "x=1"},
                "content": "Successfully wrote 3 characters."
            },
            {
                "tool": "run_command",
                "success": True,
                "arguments": {"cmd": "pytest"},
                "content": '{"success": true, "exit_code": 0, "stdout": "=== 5 passed, 0 failed in 0.1s ===", "stderr": ""}'
            }
        ],
        "verification_report": None,  # No verification report
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }

    result = await final_response_node(state)
    assert result["final_response"] == "Summary created."

    called_messages = mock_chat_service.provider.generate.call_args[0][0]
    user_msg = next(m for m in called_messages if m.role == "user")
    prompt = user_msg.content

    assert "### STRUCTURED METRICS" in prompt
    assert "result.py" in prompt
    assert "Passed: 5" in prompt
    assert "Failed: 0" in prompt
    assert "Workspace Snapshot" not in prompt  # Not available in fallback


@pytest.mark.anyio
async def test_final_response_grounding_fallback_no_files_no_tests() -> None:
    mock_chat_service = MagicMock()
    mock_chat_service.provider = MagicMock()
    mock_chat_service.provider.generate = AsyncMock()

    mock_llm_response = MagicMock(spec=AIResponse)
    mock_llm_response.content = "Summary created for read-only goal."
    mock_chat_service.provider.generate.return_value = mock_llm_response

    final_response_node = make_final_response_node(mock_chat_service)

    state: AgentState = {
        "goal": "Only read files and explain code",
        "plan": Plan(
            goal_summary="Read-only investigation",
            targets=[],
            assumptions=[],
            ordered_steps=["Read main.py"],
            risks=[],
            validation_checklist=[],
        ),
        "messages": [],
        "tool_results": [
            {
                "tool": "view_file",
                "success": True,
                "arguments": {"path": "main.py"},
                "content": "some content"
            }
        ],
        "verification_report": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }

    result = await final_response_node(state)
    assert result["final_response"] == "Summary created for read-only goal."

    called_messages = mock_chat_service.provider.generate.call_args[0][0]
    user_msg = next(m for m in called_messages if m.role == "user")
    prompt = user_msg.content

    assert "### STRUCTURED METRICS" in prompt
    assert "Files Created (0): (none)" in prompt
    assert "Files Modified (0): (none)" in prompt
    assert "Test Execution Summary: No test suites were run." in prompt

